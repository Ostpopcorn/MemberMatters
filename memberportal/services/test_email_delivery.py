from datetime import timedelta
from unittest import mock

import requests
from constance.test import override_config
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from django_celery_beat.models import IntervalSchedule, PeriodicTask
from postmarker.core import ClientError

from profile.models import UserEventLog
from services import email_delivery

BROKER_URL = "redis://:hunter2@mm-redis:6379/0"


def _checks(status):
    return {row["key"]: row for row in status["checks"]}


@override_config(
    POSTMARK_API_KEY="test-key",
    EMAIL_DEFAULT_FROM="from@example.com",
    EMAIL_ADMIN="admin@example.com",
)
class DeliveryStatusTests(TestCase):
    def setUp(self):
        self.postmark = mock.patch.object(email_delivery, "PostmarkClient").start()
        self.postmark.return_value.server.get.return_value.Name = "Makerspace Live"
        self.addCleanup(mock.patch.stopall)

    def test_rows_are_always_present_in_order(self):
        status = email_delivery.get_delivery_status()

        self.assertEqual(
            [row["key"] for row in status["checks"]],
            [
                "postmark",
                "from_address",
                "admin_address",
                "broker",
                "workers",
                "backlog",
                "beat",
            ],
        )
        self.assertEqual(status["testRecipient"], "admin@example.com")

    def test_postmark_key_shows_server_name(self):
        row = _checks(email_delivery.get_delivery_status())["postmark"]

        self.assertEqual(row["status"], email_delivery.OK)
        self.assertEqual(row["value"], 'Set (server "Makerspace Live")')
        self.assertNotIn("test-key", str(row))
        self.postmark.assert_called_once_with(
            server_token="test-key",
            timeout=email_delivery.POSTMARK_CHECK_TIMEOUT_SECONDS,
        )

    def test_rejected_postmark_key(self):
        self.postmark.return_value.server.get.side_effect = ClientError(
            "[10] Bad or missing Server API token", error_code=10
        )

        row = _checks(email_delivery.get_delivery_status())["postmark"]

        self.assertEqual(row["status"], email_delivery.ERROR)
        self.assertEqual(row["value"], "Set")
        self.assertIn("Bad or missing Server API token", row["detail"])

    def test_unreachable_postmark(self):
        self.postmark.return_value.server.get.side_effect = requests.ConnectTimeout()

        row = _checks(email_delivery.get_delivery_status())["postmark"]

        self.assertEqual(row["status"], email_delivery.ERROR)
        self.assertEqual(row["value"], "Set")
        self.assertIn("Could not reach Postmark", row["detail"])

    @override_config(POSTMARK_API_KEY="", EMAIL_DEFAULT_FROM="", EMAIL_ADMIN="")
    def test_missing_settings_show_placeholder(self):
        status = email_delivery.get_delivery_status()
        checks = _checks(status)

        for key in ("postmark", "from_address", "admin_address"):
            self.assertEqual(checks[key]["status"], email_delivery.ERROR)
            self.assertEqual(checks[key]["value"], email_delivery.NOT_AVAILABLE)
        self.postmark.assert_not_called()
        self.assertIsNone(status["testRecipient"])

    def test_shows_addresses(self):
        checks = _checks(email_delivery.get_delivery_status())

        self.assertEqual(checks["from_address"]["value"], "from@example.com")
        self.assertEqual(checks["admin_address"]["value"], "admin@example.com")

    @override_settings(CELERY_BROKER_URL=None)
    def test_without_broker_celery_rows_are_informational(self):
        status = email_delivery.get_delivery_status()
        checks = _checks(status)

        self.assertEqual(checks["broker"]["status"], email_delivery.INFO)
        self.assertEqual(checks["broker"]["value"], "Not configured")
        for key in ("workers", "backlog", "beat"):
            self.assertEqual(checks[key]["status"], email_delivery.INFO)
            self.assertEqual(checks[key]["value"], email_delivery.NOT_AVAILABLE)
        self.assertFalse(status["workerTestAvailable"])

    @override_settings(CELERY_BROKER_URL="redis://127.0.0.1:1/0")
    def test_unreachable_broker_skips_worker_checks(self):
        with mock.patch.object(email_delivery.app.control, "inspect") as inspect:
            checks = _checks(email_delivery.get_delivery_status())

        inspect.assert_not_called()
        self.assertEqual(checks["broker"]["status"], email_delivery.ERROR)
        for key in ("workers", "backlog"):
            self.assertEqual(checks[key]["status"], email_delivery.UNKNOWN)
            self.assertEqual(checks[key]["value"], email_delivery.NOT_AVAILABLE)


@override_settings(CELERY_BROKER_URL=BROKER_URL)
class CeleryChecksTests(TestCase):
    def setUp(self):
        redis_client = mock.patch.object(email_delivery.redis.Redis, "from_url").start()
        self.llen = redis_client.return_value.llen
        self.llen.return_value = 0
        self.active_queues = (
            mock.patch.object(email_delivery.app.control, "inspect")
            .start()
            .return_value.active_queues
        )
        self.active_queues.return_value = {"celery@worker1": [{"name": "celery"}]}
        self.addCleanup(mock.patch.stopall)

    def _checks(self):
        return {row["key"]: row for row in email_delivery._check_celery()}

    def test_healthy_queue_and_worker(self):
        checks = self._checks()

        self.assertEqual(checks["broker"]["status"], email_delivery.OK)
        self.assertNotIn("hunter2", checks["broker"]["value"])
        self.assertIn("mm-redis:6379", checks["broker"]["value"])
        self.assertEqual(checks["workers"]["status"], email_delivery.OK)
        self.assertEqual(checks["workers"]["value"], "1 online")
        self.assertIn("celery@worker1", checks["workers"]["detail"])
        self.assertEqual(checks["backlog"]["value"], "0 waiting")

    def test_no_worker_answers(self):
        self.active_queues.return_value = None

        row = self._checks()["workers"]

        self.assertEqual(row["status"], email_delivery.ERROR)
        self.assertEqual(row["value"], "0 online")

    def test_worker_not_reading_default_queue(self):
        self.active_queues.return_value = {"celery@worker1": [{"name": "other"}]}

        row = self._checks()["workers"]

        self.assertEqual(row["status"], email_delivery.ERROR)
        self.assertEqual(row["value"], "1 online")
        self.assertIn("'celery' queue", row["detail"])

    def test_waiting_tasks(self):
        self.llen.return_value = 3

        row = self._checks()["backlog"]

        self.assertEqual(row["status"], email_delivery.WARNING)
        self.assertEqual(row["value"], "3 waiting")

    def test_beat_never_ran(self):
        row = self._checks()["beat"]

        self.assertEqual(row["status"], email_delivery.WARNING)
        self.assertEqual(row["value"], email_delivery.NOT_AVAILABLE)

    def _heartbeat(self, last_run_ago):
        PeriodicTask.objects.create(
            name=email_delivery.HEARTBEAT_TASK_NAME,
            task="api_access.tasks.heartbeat_logger",
            interval=IntervalSchedule.objects.create(
                every=3600, period=IntervalSchedule.SECONDS
            ),
            last_run_at=timezone.now() - last_run_ago,
        )

    def test_beat_recent_heartbeat(self):
        self._heartbeat(timedelta(minutes=20))

        row = self._checks()["beat"]

        self.assertEqual(row["status"], email_delivery.OK)
        self.assertEqual(row["value"], "Heartbeat 20\xa0minutes ago")

    def test_beat_stale_heartbeat(self):
        self._heartbeat(timedelta(hours=3))

        row = self._checks()["beat"]

        self.assertEqual(row["status"], email_delivery.WARNING)
        self.assertIn("stopped", row["detail"])


@override_config(POSTMARK_API_KEY="test-key", EMAIL_ADMIN="admin@example.com")
class SendTestEmailTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            "boss@example.com", "password"
        )
        self.postmark_send = mock.patch.object(
            email_delivery, "postmark_send", return_value={"MessageID": "msg-1"}
        ).start()
        self.addCleanup(mock.patch.stopall)

    def _logs(self):
        return list(
            UserEventLog.objects.filter(user=self.admin).values_list(
                "description", flat=True
            )
        )

    def test_sends_to_email_admin_and_logs(self):
        result = email_delivery.send_test_email(self.admin, via="by the web app")

        self.assertEqual(result, {"ok": True, "messageId": "msg-1"})
        to_email, subject, html_body = self.postmark_send.call_args.args
        self.assertEqual(to_email, "admin@example.com")
        self.assertEqual(subject, email_delivery.TEST_EMAIL_SUBJECT)
        self.assertIn("boss@example.com", html_body)
        self.assertIn(
            "Sent a test email to admin@example.com by the web app.", self._logs()
        )

    def test_postmark_rejection(self):
        self.postmark_send.side_effect = ClientError(
            "[400] Sender signature not found", error_code=400
        )

        result = email_delivery.send_test_email(self.admin, via="by the web app")

        self.assertFalse(result["ok"])
        self.assertIn("Sender signature not found", result["error"])
        self.assertIn("Test email sent by the web app failed.", self._logs())

    def test_unreachable_postmark(self):
        self.postmark_send.side_effect = requests.ConnectionError("refused")

        result = email_delivery.send_test_email(self.admin, via="by the web app")

        self.assertFalse(result["ok"])
        self.assertIn("Could not reach Postmark", result["error"])

    @override_config(EMAIL_ADMIN="")
    def test_no_admin_address(self):
        result = email_delivery.send_test_email(self.admin, via="by the web app")

        self.assertFalse(result["ok"])
        self.postmark_send.assert_not_called()

    @override_config(POSTMARK_API_KEY="")
    def test_no_api_key(self):
        result = email_delivery.send_test_email(self.admin, via="by the web app")

        self.assertFalse(result["ok"])
        self.postmark_send.assert_not_called()

    def test_task_reports_result_and_worker(self):
        result = email_delivery.send_test_email_task.apply(
            kwargs={"requested_by_id": self.admin.pk}
        ).get()

        self.assertTrue(result["ok"])
        self.assertIn("worker", result)
        self.assertIn(
            "Sent a test email to admin@example.com by the Celery worker.",
            self._logs(),
        )


class TestEmailResultTests(TestCase):
    def _result(self, state, info=None):
        async_result = mock.Mock(state=state, info=info, result=info)
        with mock.patch.object(
            email_delivery, "AsyncResult", return_value=async_result
        ):
            return email_delivery.get_test_email_result("task-id")

    def test_queued(self):
        self.assertEqual(self._result("PENDING"), {"state": "PENDING"})

    def test_picked_up(self):
        self.assertEqual(
            self._result("STARTED", {"hostname": "celery@worker1", "pid": 7}),
            {"state": "STARTED", "worker": "celery@worker1"},
        )

    def test_finished(self):
        response = self._result(
            "SUCCESS", {"ok": True, "messageId": "msg-1", "worker": "celery@worker1"}
        )

        self.assertEqual(response["state"], "SUCCESS")
        self.assertTrue(response["ok"])
        self.assertEqual(response["messageId"], "msg-1")
        self.assertEqual(response["worker"], "celery@worker1")

    def test_crashed(self):
        response = self._result("FAILURE", RuntimeError("worker lost"))

        self.assertEqual(
            response, {"state": "FAILURE", "ok": False, "error": "worker lost"}
        )

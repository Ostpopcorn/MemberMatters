from unittest import mock

import requests
from celery.exceptions import Retry
from constance.test import override_config
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import SimpleTestCase, TestCase
from kombu.exceptions import OperationalError
from postmarker.core import ClientError

from profile.models import UserEventLog
from services import emails


def _http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(response=response)


def _client_error(status, error_code):
    # Mirrors postmarker, which raises ClientError from the requests.HTTPError.
    error = ClientError(f"[{error_code}] error", error_code=error_code)
    error.__cause__ = _http_error(status)
    return error


def _email_kwargs(user=None, **overrides):
    kwargs = {
        "to_email": "member@example.com",
        "subject": "Test subject",
        "template_vars": {"title": "Title", "message": "Hello"},
        "template_name": None,
        "reply_to": None,
        "user_id": user.pk if user else None,
    }
    kwargs.update(overrides)
    return kwargs


class IsTransientTests(SimpleTestCase):
    def test_network_errors_are_transient(self):
        self.assertTrue(emails._is_transient(requests.ConnectionError()))
        self.assertTrue(emails._is_transient(requests.ReadTimeout()))

    def test_rate_limit_and_server_errors_are_transient(self):
        for status in (429, 500, 503):
            self.assertTrue(emails._is_transient(_client_error(status, 0)))
        self.assertTrue(emails._is_transient(_http_error(502)))

    def test_postmark_rejections_are_not_transient(self):
        self.assertFalse(emails._is_transient(_client_error(422, 300)))
        self.assertFalse(emails._is_transient(_client_error(401, 10)))
        self.assertFalse(emails._is_transient(ValueError("bad template")))


class SendSingleEmailTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("member@example.com")

    def test_queues_after_commit_with_user_id_and_redacted_repr(self):
        with mock.patch.object(emails.send_email_task, "apply_async") as apply_async:
            with self.captureOnCommitCallbacks(execute=True):
                result = emails.send_single_email(
                    "member@example.com",
                    "Reset your password",
                    {"link": "https://portal.example.com/reset/secret-token"},
                    user=self.user,
                )
                apply_async.assert_not_called()

        self.assertTrue(result)
        apply_async.assert_called_once()
        call = apply_async.call_args.kwargs
        self.assertEqual(call["kwargs"]["user_id"], self.user.pk)
        self.assertEqual(call["kwargs"]["subject"], "Reset your password")
        self.assertNotIn("secret-token", call["kwargsrepr"])

    def test_rolled_back_transaction_sends_nothing(self):
        with mock.patch.object(emails.send_email_task, "apply_async") as apply_async:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                try:
                    with transaction.atomic():
                        emails.send_single_email("member@example.com", "Hi", {})
                        raise RuntimeError("roll back")
                except RuntimeError:
                    pass

        self.assertEqual(callbacks, [])
        apply_async.assert_not_called()

    def test_sends_inline_when_broker_is_unreachable(self):
        with mock.patch.object(
            emails.send_email_task,
            "apply_async",
            side_effect=OperationalError("connection refused"),
        ), mock.patch.object(emails, "_deliver") as deliver:
            with self.captureOnCommitCallbacks(execute=True):
                emails.send_single_email(
                    "member@example.com", "Hi", {"message": "Hello"}, user=self.user
                )

        deliver.assert_called_once()
        self.assertEqual(deliver.call_args.args[0], "member@example.com")
        self.assertEqual(deliver.call_args.args[5], self.user)


@override_config(POSTMARK_API_KEY="test-key", EMAIL_DEFAULT_FROM="from@example.com")
class SendEmailTaskTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("member@example.com")
        self.postmark = mock.patch.object(emails, "PostmarkClient").start()
        self.send = self.postmark.return_value.emails.send
        self.retry = mock.patch.object(
            emails.send_email_task, "retry", side_effect=Retry()
        ).start()
        self.addCleanup(mock.patch.stopall)

    def _logs(self):
        return list(
            UserEventLog.objects.filter(user=self.user).values_list(
                "description", flat=True
            )
        )

    def _run_in_worker(self, retries=0):
        """Runs the task body as a worker would (not eagerly)."""
        emails.send_email_task.push_request(retries=retries, is_eager=False)
        try:
            emails.send_email_task.run(**_email_kwargs(self.user))
        finally:
            emails.send_email_task.pop_request()

    def test_sends_via_postmark_with_timeout_and_logs_event(self):
        result = emails.send_email_task.apply(kwargs=_email_kwargs(self.user))

        self.assertTrue(result.successful())
        self.postmark.assert_called_once_with(
            server_token="test-key", timeout=emails.POSTMARK_TIMEOUT_SECONDS
        )
        sent = self.send.call_args.kwargs
        self.assertEqual(sent["To"], "member@example.com")
        self.assertEqual(sent["From"], "from@example.com")
        self.assertEqual(sent["Subject"], "Test subject")
        self.assertIn("Sent email with subject: Test subject", self._logs())

    def test_inactive_recipient_is_logged_but_not_reported_as_sent(self):
        self.send.side_effect = _client_error(422, 406)

        result = emails.send_email_task.apply(kwargs=_email_kwargs(self.user))

        self.assertTrue(result.successful())
        logs = self._logs()
        self.assertTrue(any("INACTIVE" in log for log in logs))
        self.assertFalse(any(log.startswith("Sent email") for log in logs))

    @override_config(POSTMARK_API_KEY="")
    def test_missing_api_key_skips_send(self):
        emails.send_email_task.apply(kwargs=_email_kwargs(self.user))

        self.postmark.assert_not_called()
        self.assertIn(
            "Email NOT sent due to configuration issue: Test subject", self._logs()
        )

    def test_deleted_user_still_gets_email_sent(self):
        result = emails.send_email_task.apply(kwargs=_email_kwargs(user_id=999999))

        self.assertTrue(result.successful())
        self.send.assert_called_once()

    def test_transient_error_in_worker_is_retried_with_backoff(self):
        self.send.side_effect = requests.ConnectionError("connection reset")

        with self.assertRaises(Retry):
            self._run_in_worker(retries=2)

        self.retry.assert_called_once()
        retry_options = self.retry.call_args.kwargs
        self.assertEqual(
            retry_options["countdown"], emails.EMAIL_RETRY_BASE_DELAY_SECONDS * 4
        )
        self.assertNotIn("Hello", retry_options["kwargsrepr"])
        self.assertEqual(self._logs(), [])

    def test_transient_error_gives_up_after_max_retries(self):
        self.send.side_effect = requests.ConnectionError("connection reset")

        with self.assertRaises(requests.ConnectionError):
            self._run_in_worker(retries=emails.EMAIL_MAX_RETRIES)

        self.retry.assert_not_called()
        self.assertIn("Email NOT sent due to an error: Test subject", self._logs())

    def test_postmark_rejection_is_not_retried(self):
        self.send.side_effect = _client_error(422, 300)

        with self.assertRaises(ClientError):
            self._run_in_worker()

        self.retry.assert_not_called()
        self.assertIn("Email NOT sent due to an error: Test subject", self._logs())

    def test_eager_task_does_not_retry_transient_errors(self):
        self.send.side_effect = requests.ConnectionError("connection reset")

        result = emails.send_email_task.apply(kwargs=_email_kwargs(self.user))

        self.assertTrue(result.failed())
        self.retry.assert_not_called()
        self.assertIn("Email NOT sent due to an error: Test subject", self._logs())

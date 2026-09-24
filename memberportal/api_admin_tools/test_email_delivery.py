from unittest import mock

from constance.test import override_config
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from services import email_delivery

STATUS_URL = "/api/admin/email-delivery/status/"
TEST_URL = "/api/admin/email-delivery/test/"
RESULT_URL = "/api/admin/email-delivery/test/3f1c8e1e-6b0e-4d8e-9d5c-2a8f4e6b7c10/"


@override_config(EMAIL_ADMIN="admin@example.com")
class EmailDeliveryViewTests(TestCase):
    def setUp(self):
        # Throttle history lives in the cache, which outlives each test.
        cache.clear()
        users = get_user_model().objects
        self.admin = users.create_superuser("boss@example.com", "password")
        self.member = users.create_user("member@example.com", "password")
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_non_admins_are_refused(self):
        self.client.force_authenticate(self.member)

        for response in (
            self.client.get(STATUS_URL),
            self.client.post(TEST_URL, {"via": "direct"}, format="json"),
            self.client.get(RESULT_URL),
        ):
            self.assertEqual(response.status_code, 403)

    def test_anonymous_users_are_refused(self):
        self.client.force_authenticate(None)

        self.assertIn(self.client.get(STATUS_URL).status_code, (401, 403))

    def test_status(self):
        with mock.patch.object(
            email_delivery, "get_delivery_status", return_value={"checks": []}
        ):
            response = self.client.get(STATUS_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"checks": []})

    def test_rejects_unknown_via(self):
        response = self.client.post(TEST_URL, {"via": "carrier-pigeon"}, format="json")

        self.assertEqual(response.status_code, 400)

    @override_config(EMAIL_ADMIN="")
    def test_rejects_test_without_admin_address(self):
        response = self.client.post(TEST_URL, {"via": "direct"}, format="json")

        self.assertEqual(response.status_code, 400)

    def test_direct_test_returns_outcome(self):
        with mock.patch.object(
            email_delivery,
            "send_test_email",
            return_value={"ok": True, "messageId": "msg-1"},
        ) as send_test_email:
            response = self.client.post(TEST_URL, {"via": "direct"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "messageId": "msg-1"})
        self.assertEqual(send_test_email.call_args.args[0], self.admin)

    @override_settings(CELERY_BROKER_URL=None)
    def test_worker_test_needs_a_queue(self):
        response = self.client.post(TEST_URL, {"via": "worker"}, format="json")

        self.assertEqual(response.status_code, 409)

    @override_settings(CELERY_BROKER_URL="redis://mm-redis:6379/0")
    def test_worker_test_returns_task_id(self):
        with mock.patch.object(
            email_delivery.send_test_email_task, "apply_async"
        ) as apply_async:
            apply_async.return_value.id = "task-1"
            response = self.client.post(TEST_URL, {"via": "worker"}, format="json")

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {"taskId": "task-1"})
        self.assertEqual(
            apply_async.call_args.kwargs["kwargs"], {"requested_by_id": self.admin.pk}
        )
        self.assertEqual(
            apply_async.call_args.kwargs["expires"],
            email_delivery.TEST_EMAIL_EXPIRES_SECONDS,
        )

    @override_settings(CELERY_BROKER_URL="redis://mm-redis:6379/0")
    def test_worker_test_reports_unreachable_queue(self):
        with mock.patch.object(
            email_delivery.send_test_email_task,
            "apply_async",
            side_effect=ConnectionError("refused"),
        ):
            response = self.client.post(TEST_URL, {"via": "worker"}, format="json")

        self.assertEqual(response.status_code, 503)
        self.assertIn("refused", response.json()["error"])

    def test_result(self):
        with mock.patch.object(
            email_delivery,
            "get_test_email_result",
            return_value={"state": "PENDING"},
        ) as get_result:
            response = self.client.get(RESULT_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"state": "PENDING"})
        get_result.assert_called_once_with("3f1c8e1e-6b0e-4d8e-9d5c-2a8f4e6b7c10")

    def test_result_needs_a_task_uuid(self):
        response = self.client.get(TEST_URL + "not-a-uuid/")

        self.assertEqual(response.status_code, 404)

    def test_test_sends_are_throttled(self):
        with mock.patch.object(
            email_delivery, "send_test_email", return_value={"ok": True}
        ):
            codes = [
                self.client.post(TEST_URL, {"via": "direct"}, format="json").status_code
                for _ in range(21)
            ]

        self.assertEqual(codes[:20], [200] * 20)
        self.assertEqual(codes[20], 429)

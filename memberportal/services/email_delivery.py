"""Checks and test sends behind the admin Email delivery page."""

from datetime import timedelta
import logging

import redis
import requests
from celery.result import AsyncResult
from constance import config
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.timesince import timesince
from django_celery_beat.models import PeriodicTask
from kombu import Connection
from postmarker.core import PostmarkClient, ClientError

from membermatters.celeryapp import app
from services.emails import postmark_send, render_email

logger = logging.getLogger("emails")

NOT_AVAILABLE = "----"
OK, WARNING, ERROR, INFO, UNKNOWN = "ok", "warning", "error", "info", "unknown"

POSTMARK_CHECK_TIMEOUT_SECONDS = 5
BROKER_CHECK_TIMEOUT_SECONDS = 2
WORKER_CHECK_TIMEOUT_SECONDS = 1

# Registered by api_access.tasks; beat bumps its last run time on every run.
HEARTBEAT_TASK_NAME = "celery_heartbeat_logger"

TEST_EMAIL_SUBJECT = "MemberMatters test email"
# A worker test nobody picks up in time is discarded rather than sent whenever
# a worker comes back (the page gives up waiting after 15 seconds).
TEST_EMAIL_EXPIRES_SECONDS = 60
BEAT_NOT_NEEDED_FOR_EMAIL = (
    "Beat runs scheduled jobs (metrics, cleanup); it isn't needed to send emails."
)


def queue_configured():
    return bool(settings.CELERY_BROKER_URL)


def _row(key, label, status, value=None, detail=""):
    return {
        "key": key,
        "label": label,
        "status": status,
        "value": value or NOT_AVAILABLE,
        "detail": detail,
    }


def _check_postmark():
    label = "Postmark API key"
    if not config.POSTMARK_API_KEY:
        return _row(
            "postmark",
            label,
            ERROR,
            detail="POSTMARK_API_KEY is not set, so no emails are sent.",
        )

    try:
        server = PostmarkClient(
            server_token=config.POSTMARK_API_KEY,
            timeout=POSTMARK_CHECK_TIMEOUT_SECONDS,
        ).server.get()
    except ClientError as e:
        return _row(
            "postmark", label, ERROR, "Set", f"Postmark rejected the API key: {e}"
        )
    except requests.RequestException as e:
        return _row("postmark", label, ERROR, "Set", f"Could not reach Postmark: {e}")

    return _row("postmark", label, OK, f'Set (server "{server.Name}")')


def _check_address(key, label, address, missing_detail):
    if address:
        return _row(key, label, OK, address)
    return _row(key, label, ERROR, detail=missing_detail)


def _check_beat():
    label = "Celery beat"
    heartbeat = PeriodicTask.objects.filter(name=HEARTBEAT_TASK_NAME).first()
    if not heartbeat or not heartbeat.last_run_at:
        return _row(
            "beat",
            label,
            WARNING,
            detail="Beat hasn't recorded a run yet. It saves its progress every "
            "few minutes, so a newly started beat shows this for a few "
            f"minutes. {BEAT_NOT_NEEDED_FOR_EMAIL}",
        )

    last_run = heartbeat.last_run_at
    value = f"Heartbeat {timesince(last_run)} ago"
    run_every = getattr(heartbeat.schedule, "run_every", None)
    # Beat saves last_run_at every few minutes, so allow some slack.
    if run_every and timezone.now() - last_run > 2 * run_every + timedelta(minutes=5):
        return _row(
            "beat",
            label,
            WARNING,
            value,
            f"Beat looks stopped. {BEAT_NOT_NEEDED_FOR_EMAIL}",
        )
    return _row("beat", label, OK, value)


def _check_celery():
    if not queue_configured():
        not_used = "Not used without a queue."
        return [
            _row(
                "broker",
                "Queue (Redis)",
                INFO,
                "Not configured",
                "MM_REDIS_HOST is not set, so the web app sends emails itself.",
            ),
            _row("workers", "Celery workers", INFO, detail=not_used),
            _row("backlog", "Waiting tasks", INFO, detail=not_used),
            _row("beat", "Celery beat", INFO, detail=not_used),
        ]

    broker_url = settings.CELERY_BROKER_URL
    queue = app.conf.task_default_queue
    try:
        client = redis.Redis.from_url(
            broker_url,
            socket_connect_timeout=BROKER_CHECK_TIMEOUT_SECONDS,
            socket_timeout=BROKER_CHECK_TIMEOUT_SECONDS,
        )
        client.ping()
        backlog = client.llen(queue)
    except redis.RedisError as e:
        skipped = "Skipped because the queue can't be reached."
        return [
            _row(
                "broker",
                "Queue (Redis)",
                ERROR,
                detail=f"Could not connect to Redis: {e}. Until it's back, the "
                "web app sends emails itself.",
            ),
            _row("workers", "Celery workers", UNKNOWN, detail=skipped),
            _row("backlog", "Waiting tasks", UNKNOWN, detail=skipped),
            _check_beat(),
        ]

    rows = [
        _row(
            "broker",
            "Queue (Redis)",
            OK,
            # as_uri() hides any password in the URL.
            f"Connected ({Connection(broker_url).as_uri()})",
        )
    ]

    try:
        replies = (
            app.control.inspect(timeout=WORKER_CHECK_TIMEOUT_SECONDS).active_queues()
            or {}
        )
    except Exception as e:
        rows.append(
            _row(
                "workers",
                "Celery workers",
                ERROR,
                detail=f"Could not ask the workers: {e}",
            )
        )
    else:
        consuming = sorted(
            worker
            for worker, queues in replies.items()
            if any(q.get("name") == queue for q in queues or [])
        )
        online = f"{len(replies)} online"
        if not replies:
            rows.append(
                _row(
                    "workers",
                    "Celery workers",
                    ERROR,
                    "0 online",
                    "No worker answered, so queued emails aren't being sent.",
                )
            )
        elif not consuming:
            rows.append(
                _row(
                    "workers",
                    "Celery workers",
                    ERROR,
                    online,
                    f"No worker reads the '{queue}' queue, so queued emails "
                    "aren't being sent.",
                )
            )
        else:
            rows.append(
                _row(
                    "workers",
                    "Celery workers",
                    OK,
                    online,
                    f"Reading the '{queue}' queue: {', '.join(consuming)}",
                )
            )

    if backlog:
        rows.append(
            _row(
                "backlog",
                "Waiting tasks",
                WARNING,
                f"{backlog} waiting",
                "Tasks waiting for a free worker. A few for a moment is normal; "
                "a growing number means the workers can't keep up or aren't "
                "running.",
            )
        )
    else:
        rows.append(_row("backlog", "Waiting tasks", OK, "0 waiting"))

    rows.append(_check_beat())
    return rows


def get_delivery_status():
    return {
        "checks": [
            _check_postmark(),
            _check_address(
                "from_address",
                "Sender address (EMAIL_DEFAULT_FROM)",
                config.EMAIL_DEFAULT_FROM,
                "EMAIL_DEFAULT_FROM is not set, so Postmark rejects every email.",
            ),
            _check_address(
                "admin_address",
                "Admin address (EMAIL_ADMIN)",
                config.EMAIL_ADMIN,
                "EMAIL_ADMIN is not set, so admin notifications and test "
                "emails have nowhere to go.",
            ),
            *_check_celery(),
        ],
        "testRecipient": config.EMAIL_ADMIN or None,
        "workerTestAvailable": queue_configured(),
    }


def send_test_email(requested_by, via):
    """Sends a test email to EMAIL_ADMIN straight to Postmark (no retries) and
    returns the outcome. `via` completes "sent ..." (e.g. "by the web app")."""
    to_email = config.EMAIL_ADMIN
    if not to_email:
        result = {
            "ok": False,
            "error": "EMAIL_ADMIN is not set, so there's nowhere to send it.",
        }
    elif not config.POSTMARK_API_KEY:
        result = {"ok": False, "error": "POSTMARK_API_KEY is not set."}
    else:
        requester = requested_by.email if requested_by else "an admin"
        sent_at = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")
        html_body = render_email(
            {
                "title": "Test email",
                "message": f"This test email was sent {via} at {sent_at}, "
                f"requested by {requester} from the Email delivery page."
                "~br~~br~If you received it, MemberMatters can deliver email.",
            }
        )
        try:
            response = postmark_send(to_email, TEST_EMAIL_SUBJECT, html_body)
            result = {"ok": True, "messageId": response.get("MessageID")}
        except ClientError as e:
            result = {"ok": False, "error": f"Postmark rejected the email: {e}"}
        except requests.RequestException as e:
            result = {"ok": False, "error": f"Could not reach Postmark: {e}"}

    if result["ok"]:
        logger.info(f"Test email sent {via} to {to_email}")
    else:
        logger.warning(f"Test email sent {via} failed: {result['error']}")

    if requested_by:
        if result["ok"]:
            requested_by.log_event(
                f"Sent a test email to {to_email} {via}.",
                "email",
                f"Postmark message ID: {result['messageId']}",
            )
        else:
            requested_by.log_event(
                f"Test email sent {via} failed.", "email", result["error"]
            )

    return result


@app.task(bind=True, track_started=True)
def send_test_email_task(self, requested_by_id):
    requested_by = get_user_model().objects.filter(pk=requested_by_id).first()
    result = send_test_email(requested_by, via="by the Celery worker")
    result["worker"] = self.request.hostname
    return result


def get_test_email_result(task_id):
    """Progress of a send_test_email_task, for the page to poll."""
    result = AsyncResult(task_id, app=app)
    response = {"state": result.state}

    if result.state == "STARTED" and isinstance(result.info, dict):
        response["worker"] = result.info.get("hostname")
    elif result.state == "SUCCESS" and isinstance(result.result, dict):
        for key in ("ok", "messageId", "error", "worker"):
            response[key] = result.result.get(key)
    elif result.state == "FAILURE":
        response.update({"ok": False, "error": str(result.result)})

    return response

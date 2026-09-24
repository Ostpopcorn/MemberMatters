from django.contrib.auth import get_user_model
from django.db import transaction
from django.template.loader import render_to_string
from django.utils.html import escape
from constance import config
from postmarker.core import PostmarkClient, ClientError
from membermatters.celeryapp import app
import requests
import logging
import json

logger = logging.getLogger("emails")

# Without a timeout a hung Postmark connection blocks forever — in a Celery
# worker that permanently ties up a pool process.
POSTMARK_TIMEOUT_SECONDS = 10

# Transient failures are retried after 30s, 60s, 120s, 240s and 480s.
EMAIL_MAX_RETRIES = 5
EMAIL_RETRY_BASE_DELAY_SECONDS = 30

# Postmark answers 429 when rate limiting and 5xx when it's having trouble.
# Any other error (bad token, invalid or inactive recipient, unconfirmed
# sender signature) will fail the same way on a retry.
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}


def _is_transient(exc):
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True

    # postmarker raises ClientError from the underlying requests.HTTPError.
    http_error = exc if isinstance(exc, requests.HTTPError) else exc.__cause__
    response = getattr(http_error, "response", None)
    return getattr(response, "status_code", None) in RETRYABLE_HTTP_STATUSES


def _redacted_kwargsrepr(to_email, subject):
    # Shown in task events and worker logs instead of the full kwargs, which
    # keeps message bodies and one-time links (password reset, email
    # verification) out of them.
    return repr({"to_email": to_email, "subject": subject})


def render_email(template_vars, template_name=None):
    """Renders an email body. Escapes the title and message in place."""
    template_to_use = template_name if template_name else "email_without_button.html"
    logger.debug("Using email template: " + template_to_use)
    logger.debug("Using template vars: " + json.dumps(template_vars))

    if template_vars.get("message"):
        template_vars["message"] = escape(template_vars["message"]).replace(
            "~br~", "<br>"
        )
    if template_vars.get("title"):
        template_vars["title"] = escape(template_vars["title"])

    return render_to_string(template_to_use, {"email": template_vars, "config": config})


def postmark_send(to_email, subject, html_body, reply_to=None):
    """Sends one rendered email via Postmark and returns Postmark's response
    (which includes the MessageID). Raises on any failure."""
    postmark = PostmarkClient(
        server_token=config.POSTMARK_API_KEY, timeout=POSTMARK_TIMEOUT_SECONDS
    )
    return postmark.emails.send(
        From=config.EMAIL_DEFAULT_FROM,
        To=to_email,
        Subject=subject,
        HtmlBody=html_body,
        ReplyTo=reply_to or config.EMAIL_DEFAULT_FROM,
    )


def _deliver(
    to_email,
    subject,
    template_vars,
    template_name=None,
    reply_to=None,
    user=None,
):
    """Renders and sends one email via Postmark. Raises on failure, except for
    an inactive recipient or a missing API key, which are logged and skipped."""
    email_string = render_email(template_vars, template_name)

    if config.POSTMARK_API_KEY:
        try:
            postmark_send(to_email, subject, email_string, reply_to)
        except ClientError as e:
            if e.error_code != 406:
                raise

            logger.warning(f"Email NOT sent because recipient is INACTIVE in postmark")
            if user:
                user.log_event(
                    "Email NOT sent because recipient is INACTIVE in postmark: ",
                    "email",
                    "Email content: " + json.dumps(template_vars),
                )
            return

        if user:
            logger.info("Email sent to " + to_email + " with subject: " + subject)
            user.log_event(
                "Sent email with subject: " + subject,
                "email",
                "Email content: " + json.dumps(template_vars),
            )
    else:
        logger.warning("No postmark API key set, not sending email")
        if user:
            user.log_event(
                "Email NOT sent due to configuration issue: " + subject,
                "email",
                "Email content: " + json.dumps(template_vars),
            )


@app.task(bind=True, ignore_result=True, max_retries=EMAIL_MAX_RETRIES)
def send_email_task(
    self,
    to_email,
    subject,
    template_vars,
    template_name=None,
    reply_to=None,
    user_id=None,
):
    user = get_user_model().objects.filter(pk=user_id).first() if user_id else None

    try:
        _deliver(to_email, subject, template_vars, template_name, reply_to, user)
    except Exception as e:
        # Eager tasks (no broker configured) run inside the web request, where
        # Celery would run each retry immediately and inline — so don't.
        if (
            _is_transient(e)
            and not self.request.is_eager
            and self.request.retries < self.max_retries
        ):
            countdown = EMAIL_RETRY_BASE_DELAY_SECONDS * 2**self.request.retries
            logger.warning(
                f"Transient error sending email with subject '{subject}', "
                f"retrying in {countdown}s: {e}"
            )
            # Retries don't inherit kwargsrepr from the original message.
            raise self.retry(
                exc=e,
                countdown=countdown,
                kwargsrepr=_redacted_kwargsrepr(to_email, subject),
            )

        logger.error(f"Error sending email with subject '{subject}': {e}")
        if user:
            user.log_event(
                "Email NOT sent due to an error: " + subject,
                "email",
                str(e),
            )
        raise


def _queue_email(email_kwargs):
    try:
        send_email_task.apply_async(
            kwargs=email_kwargs,
            kwargsrepr=_redacted_kwargsrepr(
                email_kwargs["to_email"], email_kwargs["subject"]
            ),
        )
    except Exception as e:
        # Broker unreachable (or payload not serialisable): send inline rather
        # than drop the email.
        logger.warning(
            f"Could not queue email with subject '{email_kwargs['subject']}', "
            f"sending it inline instead: {e}"
        )
        send_email_task.apply(kwargs=email_kwargs)


def send_single_email(
    to_email: object,
    subject: object,
    template_vars: object,
    template_name=None,
    reply_to=None,
    user: object | None = None,
) -> object:
    """Queues an email for the Celery worker once the current transaction
    commits (immediately outside a transaction). Returns True once queued —
    delivery failures are logged and recorded in the user's event log rather
    than raised to the caller."""
    email_kwargs = {
        "to_email": to_email,
        "subject": subject,
        "template_vars": dict(template_vars),
        "template_name": template_name,
        "reply_to": reply_to,
        "user_id": user.pk if user else None,
    }
    transaction.on_commit(lambda: _queue_email(email_kwargs))
    return True


def send_email_to_admin(
    subject: object,
    template_vars: object,
    template_name=None,
    reply_to=None,
    user: object | None = None,
) -> object:
    return send_single_email(
        config.EMAIL_ADMIN,
        subject,
        template_vars,
        template_name=template_name,
        reply_to=reply_to,
        user=user,
    )

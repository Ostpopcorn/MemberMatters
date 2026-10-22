"""The weekly digest and the scheduled tasks."""

from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from integrity import emails, store, tasks
from integrity.models import IntegrityIssue, IntegrityRun, Severity, Source
from tests.factories import ProfileFactory

from .conftest import admin_mail

pytestmark = pytest.mark.django_db


def issue(severity=Severity.WARNING, **overrides):
    values = {
        "key": f"legacy:check:{IntegrityIssue.objects.count()}",
        "check_name": "unpaid_but_active",
        "severity": severity,
        "source": Source.LEGACY,
        "message": "Unpaid in Stripe, still active here",
    }
    values.update(overrides)
    return IntegrityIssue.objects.create(**values)


class TestDigest:
    def test_lists_open_warnings_and_critical_issues(self, billing_on, outbox):
        issue(Severity.CRITICAL, profile=ProfileFactory(first_name="Anna"))
        issue(Severity.WARNING)
        issue(Severity.INFO)
        issue(Severity.WARNING, acknowledged_at=timezone.now())

        assert emails.send_digest() is True

        [mail] = admin_mail(outbox)
        assert (
            mail["Subject"]
            == "Weekly billing check: 1 critical, 1 warning, 1 info open"
        )
        assert mail["HtmlBody"].count("Unpaid in Stripe, still active here") == 2
        assert "1 acknowledged issue not listed" in mail["HtmlBody"]

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"acknowledged_at": timezone.now()}, id="acknowledged"),
            pytest.param({"severity": Severity.INFO}, id="info"),
            pytest.param({"resolved_at": timezone.now()}, id="resolved"),
        ],
    )
    def test_sends_nothing_without_open_issues_to_act_on(
        self, billing_on, outbox, overrides
    ):
        issue(**overrides)

        assert emails.send_digest() is False
        assert admin_mail(outbox) == []


class TestTasks:
    def test_runs_at_night_in_the_sites_time_zone(self, settings):
        scheduled = {}

        class Sender:
            def add_periodic_task(self, schedule, signature, **kwargs):
                scheduled[kwargs["name"]] = schedule

        tasks.setup_periodic_tasks(Sender())

        daily = scheduled["integrity_daily_checks"]
        assert daily.hour == {3} and daily.minute == {15}
        assert daily.tz == ZoneInfo(settings.TIME_ZONE)
        weekly = scheduled["integrity_weekly_digest"]
        assert weekly.day_of_week == {1}

    def test_does_nothing_while_the_check_is_off(self, db, fake_stripe):
        tasks.run_integrity_checks()

        assert IntegrityRun.objects.count() == 0
        assert fake_stripe.calls == []

    def test_the_nightly_run_clears_old_history(self, billing_on, fake_stripe):
        old = issue(resolved_at=timezone.now() - store.RETENTION - timedelta(days=1))

        tasks.run_integrity_checks()

        assert not IntegrityIssue.objects.filter(pk=old.pk).exists()
        assert IntegrityRun.objects.get().status == IntegrityRun.Status.COMPLETE

    def test_skips_quietly_while_another_run_is_running(self, billing_on, fake_stripe):
        IntegrityRun.objects.create(trigger=IntegrityRun.Trigger.SCHEDULE)

        tasks.run_integrity_checks()

        assert fake_stripe.calls == []


def test_delete_old_keeps_the_last_complete_run(db):
    long_ago = timezone.now() - store.RETENTION - timedelta(days=5)
    kept = IntegrityRun.objects.create(
        trigger=IntegrityRun.Trigger.SCHEDULE,
        status=IntegrityRun.Status.COMPLETE,
        started_at=long_ago,
        finished_at=long_ago,
    )
    dropped = IntegrityRun.objects.create(
        trigger=IntegrityRun.Trigger.SCHEDULE,
        status=IntegrityRun.Status.FAILED,
        started_at=long_ago,
    )

    store.delete_old(timezone.now())

    assert IntegrityRun.objects.filter(pk=kept.pk).exists()
    assert not IntegrityRun.objects.filter(pk=dropped.pk).exists()

"""Run a plan price change in the foreground, without Celery.

For when the worker or broker is down, or to watch a run's output directly.
It runs the same code as the Celery task, so it is safe to use on a job that
is also queued: only one run can claim the job at a time.

Example:

    python3 manage.py run_plan_price_change 12
"""

from django.core.management.base import BaseCommand, CommandError

from api_billing.models import PlanPriceChange
from api_billing.price_change import run_price_change


class Command(BaseCommand):
    help = "Move a plan's subscriptions to its new price (see PlanPriceChange)."

    def add_arguments(self, parser):
        parser.add_argument("job_id", type=int)

    def handle(self, *args, job_id, **options):
        if not PlanPriceChange.objects.filter(pk=job_id).exists():
            raise CommandError(f"No price change with id {job_id}.")

        job = run_price_change(job_id)
        if job is None:
            raise CommandError(
                f"Price change {job_id} is already completed or another run "
                "is in progress."
            )

        self.stdout.write(
            f"Price change {job.pk}: {job.status}. Moved {job.migrated_count}, "
            f"{job.remaining_count} still on the old price."
        )
        for failure in job.failures:
            self.stdout.write(
                f"  {failure['subscription']} "
                f"({failure['member'] or failure['customer']}): {failure['error']}"
            )
        if job.error:
            self.stdout.write(job.error)

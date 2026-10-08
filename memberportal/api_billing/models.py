from django.db import models


class ProcessedStripeEvent(models.Model):
    """Idempotency record for Stripe webhook events.

    Stripe retries webhook deliveries on non-2xx responses or timeouts for up
    to ~3 days. We store every successfully-validated event id here and
    skip duplicates so retries don't re-run side effects (emails, SMS, state
    changes). Cleaned up periodically by an admin/cron task."""

    event_id = models.CharField(max_length=255, primary_key=True)
    event_type = models.CharField(max_length=100)
    processed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Processed Stripe Event"
        verbose_name_plural = "Processed Stripe Events"


class PlanPriceChange(models.Model):
    """An admin's change to a payment plan's price, and its rollout.

    Stripe prices are immutable, so a new price means a new Price object and
    moving every live subscription across to it. That is one Stripe call per
    subscription, so it runs in the background (api_billing.tasks) and this
    row records how far it has got. A run that stops early can be resumed:
    Stripe itself is the record of which subscriptions are still on the old
    price, so a resumed run picks up exactly those.
    """

    class Status(models.TextChoices):
        # Queued; no run has started yet.
        PENDING = "pending"
        RUNNING = "running"
        # Every subscription moved and the old price archived.
        COMPLETED = "completed"
        # A run finished but some subscriptions could not be moved.
        PARTIAL = "partial"
        # A run stopped early, e.g. Stripe kept failing. Safe to resume.
        INTERRUPTED = "interrupted"

    plan = models.ForeignKey(
        "api_admin_tools.PaymentPlan",
        on_delete=models.CASCADE,
        related_name="price_changes",
    )
    old_price_id = models.CharField(max_length=100)
    new_price_id = models.CharField(max_length=100)
    old_cost = models.IntegerField("Old cost in cents")
    new_cost = models.IntegerField("New cost in cents")
    currency = models.CharField(max_length=3)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    # Incremented by each run; part of the idempotency key, so a resumed run
    # gets a fresh attempt rather than Stripe replaying the earlier result.
    runs = models.PositiveIntegerField(default=0)
    migrated_count = models.PositiveIntegerField(default=0)
    # Subscriptions still on the old price as of the latest run.
    remaining_count = models.PositiveIntegerField(default=0)
    # [{subscription, customer, member, error}] from the latest run.
    failures = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        "profile.User", null=True, blank=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.plan} {self.old_cost} -> {self.new_cost} ({self.status})"

    def get_object(self):
        return {
            "id": self.id,
            "plan": self.plan_id,
            "oldPriceId": self.old_price_id,
            "newPriceId": self.new_price_id,
            "oldCost": self.old_cost,
            "newCost": self.new_cost,
            "currency": self.currency,
            "status": self.status,
            "runs": self.runs,
            "migratedCount": self.migrated_count,
            "remainingCount": self.remaining_count,
            "failures": self.failures,
            "error": self.error,
            "createdBy": self.created_by.get_full_name() if self.created_by else None,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "finishedAt": self.finished_at,
        }

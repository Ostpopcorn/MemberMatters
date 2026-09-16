from django.db import models
from datetime import timedelta
from django.utils import timezone
import pytz
from django.conf import settings
from uuid import uuid4
from django_prometheus.models import ExportModelOperationsMixin

utc = pytz.UTC


class Kiosk(ExportModelOperationsMixin("kiosk"), models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField("Name", max_length=30, unique=True)
    kiosk_id = models.CharField("Kiosk Id", max_length=70, unique=True)
    ip_address = models.GenericIPAddressField(
        "IP Address of device", unique=True, null=True, blank=True
    )
    last_seen = models.DateTimeField(null=True)
    play_theme = models.BooleanField("Play theme on door swipe", default=False)
    authorised = models.BooleanField("Is this kiosk authorised?", default=False)

    def checkin(self):
        self.last_seen = timezone.now()
        self.save()

    def get_unavailable(self):
        if self.last_seen:
            if timezone.now() - timedelta(minutes=5) > self.last_seen:
                return True

        return False

    def __str__(self):
        return self.name


class SiteSession(ExportModelOperationsMixin("site-session"), models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    signin_date = models.DateTimeField(default=timezone.now)
    signout_date = models.DateTimeField(null=True, blank=True)
    guests = models.TextField(default="[]")

    def signout(self):
        self.signout_date = timezone.now()
        self.save()

    def __str__(self):
        return f"{self.user.profile.get_full_name()} - in: {self.signin_date} out: {self.signout_date}"


class DashboardCard(ExportModelOperationsMixin("dashboard-card"), models.Model):
    """A card in the "Member Resources" section of the member dashboard."""

    id = models.AutoField(primary_key=True)
    position = models.PositiveIntegerField("Position", default=0)
    enabled = models.BooleanField("Shown on the dashboard", default=True)
    title = models.CharField("Title", max_length=255)
    icon = models.CharField("Icon", max_length=100)
    description = models.TextField("Description (HTML)", blank=True)
    # [{"label": str, "url": str}] for an external link or
    # [{"label": str, "route": str}] for a portal page, by Vue route name.
    links = models.JSONField("Links", default=list, blank=True)

    class Meta:
        ordering = ["position", "id"]

    def get_object(self):
        return {
            "id": self.id,
            "title": self.title,
            "icon": self.icon,
            "description": self.description,
            "links": self.links,
        }

    def get_admin_object(self):
        return {
            **self.get_object(),
            "enabled": self.enabled,
            "position": self.position,
        }

    def __str__(self):
        return self.title


class EmailVerificationToken(
    ExportModelOperationsMixin("email-verification-token"), models.Model
):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    creation_date = models.DateTimeField(default=timezone.now)
    verification_token = models.UUIDField(default=uuid4)

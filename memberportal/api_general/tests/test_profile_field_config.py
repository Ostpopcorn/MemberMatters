"""The profile field settings as the public site config reports them."""

import pytest
from constance.test import override_config
from django.urls import reverse

pytestmark = pytest.mark.django_db


def get_features(api_client):
    response = api_client.get(reverse("get_config"))
    assert response.status_code == 200
    return response.json()["features"]


class TestOldFlags:
    """The flags the forms read until they use the field settings directly.

    They are worked out from the PROFILE_FIELD_* settings, so the frontend
    keeps working unchanged while it still reads them.
    """

    def test_the_defaults_match_the_old_switches_defaults(self, api_client):
        features = get_features(api_client)

        assert features["signup"]["requireScreenName"] is True
        assert features["signup"]["collectVehicleRegistrationPlate"] is False
        assert features["profile"] == {
            "canEditBasicDetails": True,
            "canEditEmail": True,
        }

    @override_config(
        PROFILE_FIELD_SCREEN_NAME="optional", PROFILE_FIELD_VEHICLE_PLATE="optional"
    )
    def test_an_optional_screen_name_and_a_collected_plate(self, api_client):
        features = get_features(api_client)

        assert features["signup"]["requireScreenName"] is False
        assert features["signup"]["collectVehicleRegistrationPlate"] is True

    @override_config(
        PROFILE_FIELD_NAME="required_admin_edits",
        PROFILE_FIELD_EMAIL="required_admin_edits",
    )
    def test_locked_details(self, api_client):
        assert get_features(api_client)["profile"] == {
            "canEditBasicDetails": False,
            "canEditEmail": False,
        }

    @override_config(PROFILE_FIELD_EMAIL="required_admin_edits")
    def test_only_the_email_locked(self, api_client):
        assert get_features(api_client)["profile"] == {
            "canEditBasicDetails": True,
            "canEditEmail": False,
        }


class TestProfileFields:
    def test_every_field_and_its_setting_is_listed(self, api_client):
        assert get_features(api_client)["profileFields"] == {
            "email": "required",
            "firstName": "required",
            "lastName": "required",
            "phone": "required",
            "screenName": "required",
            "vehicleRegistrationPlate": "hidden",
            "address": "hidden",
        }

    @override_config(
        PROFILE_FIELD_NAME="required_admin_edits",
        PROFILE_FIELD_PHONE="optional_admin_edits",
        PROFILE_FIELD_ADDRESS="optional",
    )
    def test_the_settings_are_reported_as_they_are(self, api_client):
        fields = get_features(api_client)["profileFields"]

        assert fields["firstName"] == "required_admin_edits"
        assert fields["lastName"] == "required_admin_edits"
        assert fields["phone"] == "optional_admin_edits"
        assert fields["address"] == "optional"

    @override_config(PROFILE_FIELD_PHONE="nonsense")
    def test_a_value_the_field_does_not_allow_is_reported_as_the_default(
        self, api_client
    ):
        assert get_features(api_client)["profileFields"]["phone"] == "required"

    def test_the_address_parts_are_listed_in_order(self, api_client):
        assert get_features(api_client)["addressParts"] == [
            {"key": "line1", "required": True, "maxLength": 200},
            {"key": "line2", "required": False, "maxLength": 200},
            {"key": "postal_code", "required": True, "maxLength": 20},
            {"key": "city", "required": True, "maxLength": 100},
            {"key": "country", "required": True, "maxLength": 2},
        ]

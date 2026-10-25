"""The profile field list: its cleanup functions and the PROFILE_FIELD_* settings.

Signup, the member's own edit and the admin edit all read these, so a value
cleaned differently here would be stored differently everywhere.
"""

import pytest
from constance.test import override_config
from django.conf import settings

from profile import profile_fields
from profile.profile_fields import (
    FIELDS,
    FieldError,
    clean_email,
    clean_first_name,
    clean_phone,
    clean_screen_name,
    clean_vehicle_plate,
    field_mode,
    setting_modes,
)

pytestmark = pytest.mark.django_db


def error_key(clean, value):
    with pytest.raises(FieldError) as excinfo:
        clean(value)
    return excinfo.value.key


class TestCleanEmail:
    def test_it_is_trimmed_and_lowercased(self):
        assert clean_email("  Member@Example.COM ") == "member@example.com"

    def test_blank_and_none_are_empty(self):
        assert clean_email("") == ""
        assert clean_email(None) == ""

    def test_an_invalid_address_is_refused(self):
        assert error_key(clean_email, "not-an-email") == "validation.invalidEmail"

    def test_an_address_over_255_characters_is_refused(self):
        address = "a" * 250 + "@example.com"

        assert error_key(clean_email, address) == "error.emailTooLong"


class TestCleanText:
    def test_names_are_trimmed(self):
        assert clean_first_name("  Ada ") == "Ada"

    def test_a_name_over_30_characters_is_refused(self):
        assert error_key(clean_first_name, "a" * 31) == "error.firstNameTooLong"

    def test_a_blank_screen_name_is_stored_as_null(self):
        # NULL, so members without one don't collide on the unique constraint.
        assert clean_screen_name("   ") is None
        assert clean_screen_name(None) is None

    def test_a_screen_name_is_trimmed(self):
        assert clean_screen_name(" ada ") == "ada"

    def test_a_vehicle_plate_is_trimmed(self):
        assert clean_vehicle_plate(" ABC123 ") == "ABC123"

    @pytest.mark.parametrize("value", [42, ["Ada"], {"first": "Ada"}, True])
    def test_anything_but_text_is_refused(self, value):
        assert error_key(clean_first_name, value) == "error.invalidValue"


class TestCleanPhone:
    @override_config(PROFILE_DEFAULT_PHONE_REGION="SE")
    def test_a_national_number_is_read_in_the_default_region(self):
        assert clean_phone("070-123 45 67") == "+46701234567"

    @override_config(PROFILE_DEFAULT_PHONE_REGION="SE")
    def test_an_international_number_keeps_its_own_country(self):
        assert clean_phone("+61 417 123 456") == "+61417123456"

    def test_blank_is_empty(self):
        assert clean_phone("  ") == ""
        assert clean_phone(None) == ""

    @pytest.mark.parametrize("value", ["12", "not a number", "1" * 40])
    def test_an_invalid_number_is_refused(self, value):
        assert error_key(clean_phone, value) == "validation.invalidPhone"


class TestSettings:
    @pytest.mark.parametrize("field", FIELDS, ids=lambda field: field.key)
    def test_every_field_has_a_setting_with_a_default_it_allows(self, field):
        default, _help, field_type = settings.CONSTANCE_CONFIG[field.setting]

        assert default in field.modes
        # The dropdown in the settings page offers exactly the field's values.
        choices = settings.CONSTANCE_ADDITIONAL_FIELDS[field_type][1]["choices"]
        assert tuple(value for value, _label in choices) == field.modes

    def test_the_reserved_admin_enters_values_are_not_offered_yet(self):
        offered = {mode for field in FIELDS for mode in field.modes}

        assert profile_fields.OPTIONAL_ADMIN_ENTERS not in offered
        assert profile_fields.REQUIRED_ADMIN_ENTERS not in offered

    def test_first_and_last_name_share_one_setting(self):
        fields = {field.key: field for field in FIELDS}

        assert fields["firstName"].setting == fields["lastName"].setting

    def test_setting_modes_is_none_for_other_settings(self):
        assert setting_modes("SITE_NAME") is None
        assert setting_modes("PROFILE_FIELD_EMAIL") == profile_fields.IDENTITY_MODES


class TestFieldMode:
    @override_config(PROFILE_FIELD_PHONE="optional_admin_edits")
    def test_it_is_the_setting(self):
        assert field_mode("phone") == "optional_admin_edits"

    @override_config(PROFILE_FIELD_SCREEN_NAME="nonsense")
    def test_a_value_the_field_does_not_allow_falls_back_to_the_default(self, caplog):
        assert field_mode("screenName") == "required"

        warnings = [r.getMessage() for r in caplog.records if r.name == "profile"]
        assert any("PROFILE_FIELD_SCREEN_NAME" in w for w in warnings)

    @override_config(PROFILE_FIELD_EMAIL="hidden")
    def test_a_value_only_other_fields_allow_falls_back_too(self):
        # Hidden is a real value, but the email can't be hidden.
        assert field_mode("email") == "required"

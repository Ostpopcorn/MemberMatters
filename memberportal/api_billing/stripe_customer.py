"""The member details a Stripe customer holds.

Stripe gets the email, the name (first and last together), the phone number
and the address, from the profile fields. A hidden field is never sent.
"""

from profile.profile_fields import HIDDEN, field_mode


def customer_details(values):
    """The Stripe customer fields for a member's profile values.

    `values` is {field key: value}, as profile_changes.stored_values() gives
    it. Hidden and blank fields are left out.
    """
    details = {
        "email": values["email"],
        "name": f"{values['firstName']} {values['lastName']}",
    }
    if field_mode("phone") != HIDDEN and values.get("phone"):
        details["phone"] = values["phone"]
    if field_mode("address") != HIDDEN and values.get("address"):
        details["address"] = dict(values["address"])
    return details

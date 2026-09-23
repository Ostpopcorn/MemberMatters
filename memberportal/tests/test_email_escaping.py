"""Email titles and messages are HTML-escaped exactly once, whichever template
renders them."""

import pytest

pytestmark = pytest.mark.django_db

TEXT = "O'Brien & <co>"
ESCAPED = "O&#x27;Brien &amp; &lt;co&gt;"

SENDS = {
    "with_button": lambda user: user.email_link(
        "Subject", TEXT, TEXT, "https://example.com", "Button"
    ),
    "without_button": lambda user: user.email_notification(TEXT, TEXT),
}


@pytest.mark.parametrize("send", SENDS.values(), ids=SENDS.keys())
def test_the_title_and_message_are_escaped_once(member, outbox, send):
    send(member.user)

    [message] = outbox
    body = message["HtmlBody"]
    # Once in the heading, once in the message.
    assert body.count(ESCAPED) == 2
    assert "&amp;#x27;" not in body
    assert TEXT not in body

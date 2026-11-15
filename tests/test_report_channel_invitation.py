import pytest

from smart_reporting.report_channel_invitation import Invitation, parse_channel_invitation

ORIGIN = "https://reports.example.test"
REFERENCE = "A" * 43


def test_invite_link_redeems_only_against_pinned_service():
    assert parse_channel_invitation(
        f"{ORIGIN}/reports/join#{REFERENCE}", origin=ORIGIN
    ) == REFERENCE


@pytest.mark.parametrize("link", [
    f"https://elsewhere.example.test/reports/join#{REFERENCE}",
    f"https://name@reports.example.test/reports/join#{REFERENCE}",
    f"{ORIGIN}/reports/join?next=https://elsewhere.example.test#{REFERENCE}",
    f"{ORIGIN}/other#{REFERENCE}",
    f"{ORIGIN}/reports/join#short",
])
def test_rejects_links_outside_invitation_contract(link):
    with pytest.raises(ValueError):
        parse_channel_invitation(link, origin=ORIGIN)


def test_exchange_binds_authenticated_connector_session():
    invite = Invitation("report-channel-a", "dsh", "account-a", expires_at=100)
    with pytest.raises(ValueError):
        invite.exchange(connector="dsh", subject="account-b", session="session-a", now=99)
    with pytest.raises(ValueError):
        invite.exchange(connector="dsh", subject="account-a", session="session-a", now=100)
    member = invite.exchange(connector="dsh", subject="account-a", session="session-a", now=99)
    assert (member.channel, member.connector, member.subject, member.session) == (
        "report-channel-a", "dsh", "account-a", "session-a",
    )
    with pytest.raises(ValueError):
        invite.exchange(connector="dsh", subject="account-a", session="session-b", now=99)

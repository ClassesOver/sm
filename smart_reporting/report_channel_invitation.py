"""Parse report channel invitations before passing them to a connector."""

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ChannelMember:
    channel: str
    connector: str
    subject: str
    session: str


@dataclass
class Invitation:
    """One invitation's exchange rules. The caller owns persistence and locking."""

    channel: str
    connector: str
    subject: str
    expires_at: float
    _used: bool = field(default=False, init=False)

    def exchange(self, *, connector: str, subject: str, session: str, now: float) -> ChannelMember:
        """Bind an authenticated connector session to the invitation's channel."""
        if self._used or now >= self.expires_at or not session:
            raise ValueError("invalid_report_channel_invitation")
        if (connector, subject) != (self.connector, self.subject):
            raise ValueError("invalid_report_channel_invitation")
        member = ChannelMember(self.channel, connector, subject, session)
        self._used = True
        return member


def parse_channel_invitation(link: str, *, origin: str) -> str:
    """Return the opaque fragment from an invitation at the configured origin."""
    prefix = origin.rstrip("/") + "/reports/join#"
    if link.startswith(prefix):
        reference = link[len(prefix):]
        if re.fullmatch(r"[A-Za-z0-9_-]{43}", reference):
            return reference
    raise ValueError("invalid_report_channel_invitation")

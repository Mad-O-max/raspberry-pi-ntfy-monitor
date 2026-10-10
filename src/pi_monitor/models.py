from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SshEvent:
    timestamp: datetime
    event_type: str
    username: str | None = None
    source_ip: str | None = None
    auth_method: str | None = None


@dataclass(frozen=True)
class BanEvent:
    source_ip: str
    jail: str


@dataclass(frozen=True)
class RebootReason:
    classification: str
    confidence: str
    evidence: tuple[str, ...]

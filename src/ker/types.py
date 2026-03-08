from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class InboundMessage:
    text: str
    sender_id: str
    channel: str = ""
    user: str = ""
    session_name: str = "default"
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    media: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutboundMessage:
    text: str
    channel: str = ""
    user: str = ""
    session_name: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)
    media: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ProviderBlock:
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderResponse:
    stop_reason: str
    content: list[ProviderBlock]

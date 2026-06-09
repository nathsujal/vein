from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    name: str
    healthy: bool
    latency_ms: float
    detail: str
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
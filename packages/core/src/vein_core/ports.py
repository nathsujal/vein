from __future__ import annotations

from typing import Protocol, runtime_checkable

from .domain import ServiceStatus

@runtime_checkable
class Probeable(Protocol):
    """Structural protocol for any service that can report its own health."""
    async def probe(self) -> ServiceStatus:
        # Probe this service and return its current health status
        ...

    async def close(self) -> None:
        # Release any resources held by this adapter
        ...


@runtime_checkable
class ModelVerifiable(Protocol):
    """Structural protocol that can verify whether a specific model is available"""
    @property
    def available_models(self) -> list[str]:
        # list of available models from the last successful probe, or empty if unknown
        ...
    
    async def verify_model(self, model: str) -> ServiceStatus:
        # check that *model* is available on this service
        ...
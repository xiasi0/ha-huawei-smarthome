"""Stable API exposed to user-contributed product adapters."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .context import DeviceContext


StateReader = Callable[["DeviceContext"], Mapping[str, Any]]
EntityAction = Callable[["DeviceContext", Mapping[str, Any]], Awaitable[None]]
EventDecoder = Callable[
    ["DeviceContext", str, Mapping[str, Any], str | None],
    Iterable[tuple[str, Mapping[str, Any]]],
]


@dataclass(frozen=True, slots=True)
class EntitySpec:
    """One HA entity declared by a product adapter."""

    platform: str
    key: str
    name: str | None
    state: StateReader
    metadata: Mapping[str, Any] = field(default_factory=dict)
    actions: Mapping[str, EntityAction] = field(default_factory=dict)
    event_decoder: EventDecoder | None = None


class HuaweiProductAdapter(Protocol):
    """Interface implemented by one ``prod_<prodId>.py`` file."""

    prod_id: str

    def entities(self, context: "DeviceContext") -> tuple[EntitySpec, ...]:
        """Return the entities for one device instance."""

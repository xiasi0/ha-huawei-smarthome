"""Generic Home Assistant lock registration for product adapters."""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity_helpers import AdapterEntityMixin, iter_specs


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    del hass
    async_add_entities(HuaweiAdapterLock(context, spec) for context, spec in iter_specs(entry.runtime_data, "lock"))


class HuaweiAdapterLock(AdapterEntityMixin, LockEntity):
    def __init__(self, context: Any, spec: Any) -> None: self._init_adapter_entity(context, spec)
    @property
    def is_locked(self): return self._state_value("is_locked")
    async def async_lock(self, **kwargs: Any): await self._run_action("lock", kwargs)
    async def async_unlock(self, **kwargs: Any): await self._run_action("unlock", kwargs)

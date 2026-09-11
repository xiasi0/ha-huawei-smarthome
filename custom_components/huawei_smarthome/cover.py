"""Generic Home Assistant cover registration for product adapters."""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import CoverEntity, CoverEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity_helpers import AdapterEntityMixin, iter_specs


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    del hass
    async_add_entities(HuaweiAdapterCover(context, spec) for context, spec in iter_specs(entry.runtime_data, "cover"))


class HuaweiAdapterCover(AdapterEntityMixin, CoverEntity):
    def __init__(self, context: Any, spec: Any) -> None:
        self._init_adapter_entity(context, spec)
        features = CoverEntityFeature(0)
        for action, feature in (("open", CoverEntityFeature.OPEN), ("close", CoverEntityFeature.CLOSE), ("stop", CoverEntityFeature.STOP), ("set_position", CoverEntityFeature.SET_POSITION)):
            if action in spec.actions:
                features |= feature
        self._attr_supported_features = features

    @property
    def is_closed(self): return self._state_value("is_closed")
    @property
    def current_cover_position(self): return self._state_value("current_position")
    async def async_open_cover(self, **kwargs: Any) -> None: await self._run_action("open", kwargs)
    async def async_close_cover(self, **kwargs: Any) -> None: await self._run_action("close", kwargs)
    async def async_stop_cover(self, **kwargs: Any) -> None: await self._run_action("stop", kwargs)
    async def async_set_cover_position(self, **kwargs: Any) -> None: await self._run_action("set_position", kwargs)

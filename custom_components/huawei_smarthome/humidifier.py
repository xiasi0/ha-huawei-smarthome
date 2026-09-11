"""Generic Home Assistant humidifier registration for product adapters."""

from __future__ import annotations

from typing import Any

from homeassistant.components.humidifier import HumidifierEntity, HumidifierEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity_helpers import AdapterEntityMixin, iter_specs


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    del hass
    async_add_entities(HuaweiAdapterHumidifier(context, spec) for context, spec in iter_specs(entry.runtime_data, "humidifier"))


class HuaweiAdapterHumidifier(AdapterEntityMixin, HumidifierEntity):
    def __init__(self, context: Any, spec: Any) -> None:
        self._init_adapter_entity(context, spec)
        self._attr_supported_features = HumidifierEntityFeature.MODES if spec.metadata.get("modes") else HumidifierEntityFeature(0)
        self._attr_min_humidity = spec.metadata.get("min_humidity", 0)
        self._attr_max_humidity = spec.metadata.get("max_humidity", 100)
        self._attr_available_modes = list(spec.metadata.get("modes", ()))

    @property
    def is_on(self): return self._state_value("is_on")
    @property
    def current_humidity(self): return self._state_value("current_humidity")
    @property
    def target_humidity(self): return self._state_value("target_humidity")
    @property
    def mode(self): return self._state_value("mode")
    async def async_turn_on(self): await self._run_action("turn_on", {})
    async def async_turn_off(self): await self._run_action("turn_off", {})
    async def async_set_humidity(self, humidity: int): await self._run_action("set_humidity", {"humidity": humidity})
    async def async_set_mode(self, mode: str): await self._run_action("set_mode", {"mode": mode})

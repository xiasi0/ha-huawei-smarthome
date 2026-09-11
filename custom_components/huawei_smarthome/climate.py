"""Generic Home Assistant climate registration for product adapters."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import ATTR_TEMPERATURE, ClimateEntity, ClimateEntityFeature, HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity_helpers import AdapterEntityMixin, iter_specs


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    del hass
    async_add_entities(HuaweiAdapterClimate(context, spec) for context, spec in iter_specs(entry.runtime_data, "climate"))


class HuaweiAdapterClimate(AdapterEntityMixin, ClimateEntity):
    def __init__(self, context: Any, spec: Any) -> None:
        self._init_adapter_entity(context, spec)
        metadata = spec.metadata
        self._attr_hvac_modes = list(metadata.get("hvac_modes", (HVACMode.AUTO,)))
        self._attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
        if metadata.get("fan_modes"):
            self._attr_supported_features |= ClimateEntityFeature.FAN_MODE
        if metadata.get("swing_modes"):
            self._attr_supported_features |= ClimateEntityFeature.SWING_MODE
        if "turn_on" in spec.actions:
            self._attr_supported_features |= ClimateEntityFeature.TURN_ON
        if "turn_off" in spec.actions:
            self._attr_supported_features |= ClimateEntityFeature.TURN_OFF
        self._attr_fan_modes = list(metadata.get("fan_modes", ()))
        self._attr_swing_modes = list(metadata.get("swing_modes", ()))
        self._attr_min_temp = metadata.get("min_temp")
        self._attr_max_temp = metadata.get("max_temp")

    @property
    def current_temperature(self): return self._state_value("current_temperature")
    @property
    def target_temperature(self): return self._state_value("target_temperature")
    @property
    def hvac_mode(self): return self._state_value("hvac_mode", self._attr_hvac_modes[0])
    @property
    def hvac_action(self): return self._state_value("hvac_action")
    @property
    def fan_mode(self): return self._state_value("fan_mode")
    @property
    def swing_mode(self): return self._state_value("swing_mode")

    async def async_set_temperature(self, **kwargs: Any) -> None:
        await self._run_action("set_temperature", {"temperature": kwargs.get(ATTR_TEMPERATURE)})
    async def async_set_hvac_mode(self, hvac_mode: str) -> None:
        await self._run_action("set_hvac_mode", {"hvac_mode": hvac_mode})
    async def async_set_fan_mode(self, fan_mode: str) -> None:
        await self._run_action("set_fan_mode", {"fan_mode": fan_mode})
    async def async_set_swing_mode(self, swing_mode: str) -> None:
        await self._run_action("set_swing_mode", {"swing_mode": swing_mode})
    async def async_turn_on(self) -> None:
        await self._run_action("turn_on", {})
    async def async_turn_off(self) -> None:
        await self._run_action("turn_off", {})

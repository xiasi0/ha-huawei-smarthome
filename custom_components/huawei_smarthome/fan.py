"""Generic Home Assistant fan registration for product adapters."""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity_helpers import device_info, iter_specs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    del hass
    async_add_entities(
        HuaweiAdapterFan(context, spec)
        for context, spec in iter_specs(entry.runtime_data, "fan")
    )


class HuaweiAdapterFan(FanEntity):
    def __init__(self, context: Any, spec: Any) -> None:
        self._device_context = context
        self._spec = spec
        metadata = spec.metadata
        self._attr_unique_id = f"{context.home_id}_{context.dev_id}_{spec.key}"
        self._attr_name = spec.name or context.name
        self._attr_has_entity_name = True
        self._attr_should_poll = False
        features = FanEntityFeature(0)
        if "turn_on" in spec.actions:
            features |= FanEntityFeature.TURN_ON
        if "turn_off" in spec.actions:
            features |= FanEntityFeature.TURN_OFF
        if metadata.get("supports_percentage"):
            features |= FanEntityFeature.SET_SPEED
            if metadata.get("percentage_step") is not None:
                self._attr_percentage_step = int(metadata["percentage_step"])
        if metadata.get("preset_modes"):
            features |= FanEntityFeature.PRESET_MODE
        if metadata.get("supports_oscillation"):
            features |= FanEntityFeature.OSCILLATE
        self._attr_supported_features = features
        self._attr_preset_modes = list(metadata.get("preset_modes", ()))

    @property
    def device_info(self):
        return device_info(self._device_context)

    @property
    def available(self) -> bool:
        return self._device_context.available

    def _state(self, key: str, default: Any = None) -> Any:
        return self._spec.state(self._device_context).get(key, default)

    @property
    def is_on(self) -> bool | None:
        return self._state("is_on")

    @property
    def percentage(self) -> int | None:
        return self._state("percentage")

    @property
    def preset_mode(self) -> str | None:
        return self._state("preset_mode")

    @property
    def oscillating(self) -> bool | None:
        return self._state("oscillating")

    async def async_added_to_hass(self) -> None:
        self._device_context.add_state_listener(self._state_changed)

    async def async_will_remove_from_hass(self) -> None:
        self._device_context.remove_state_listener(self._state_changed)

    async def async_turn_on(self, percentage: int | None = None, preset_mode: str | None = None, **kwargs: Any) -> None:
        del kwargs
        action = self._spec.actions.get("turn_on")
        if action is not None:
            await action(self._device_context, {"percentage": percentage, "preset_mode": preset_mode})

    async def async_turn_off(self, **kwargs: Any) -> None:
        del kwargs
        action = self._spec.actions.get("turn_off")
        if action is not None:
            await action(self._device_context, {})

    async def async_set_percentage(self, percentage: int) -> None:
        action = self._spec.actions.get("set_percentage")
        if action is None:
            raise ValueError("fan percentage action is unavailable")
        await action(self._device_context, {"percentage": percentage})

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        action = self._spec.actions.get("set_preset_mode")
        if action is None:
            raise ValueError("fan preset action is unavailable")
        await action(self._device_context, {"preset_mode": preset_mode})

    async def async_oscillate(self, oscillating: bool) -> None:
        action = self._spec.actions.get("oscillate")
        if action is None:
            raise ValueError("fan oscillation action is unavailable")
        await action(self._device_context, {"oscillating": oscillating})

    def _state_changed(self) -> None:
        self.async_write_ha_state()

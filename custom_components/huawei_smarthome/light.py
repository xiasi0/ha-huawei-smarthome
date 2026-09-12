"""Generic Home Assistant light registration for product adapters."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    filter_supported_color_modes,
)
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
        HuaweiAdapterLight(context, spec)
        for context, spec in iter_specs(entry.runtime_data, "light")
    )


class HuaweiAdapterLight(LightEntity):
    def __init__(self, context: Any, spec: Any) -> None:
        self._device_context = context
        self._spec = spec
        metadata = spec.metadata
        self._attr_unique_id = f"{context.home_id}_{context.dev_id}_{spec.key}"
        self._attr_name = spec.name or context.name
        self._attr_has_entity_name = True
        self._attr_should_poll = False
        modes = {
            ColorMode(mode)
            for mode in metadata.get("supported_color_modes", {"onoff"})
        }
        # Use HA's own capability normalization.  Product adapters still
        # declare the device capability; this only removes HA-implied ONOFF
        # and BRIGHTNESS modes before LightEntity validates the set.
        self._attr_supported_color_modes = filter_supported_color_modes(modes)
        if metadata.get("min_color_temp_kelvin") is not None:
            self._attr_min_color_temp_kelvin = int(
                metadata["min_color_temp_kelvin"]
            )
        if metadata.get("max_color_temp_kelvin") is not None:
            self._attr_max_color_temp_kelvin = int(
                metadata["max_color_temp_kelvin"]
            )

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
    def brightness(self) -> int | None:
        return self._state("brightness")

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        value = self._state("rgb_color")
        if not isinstance(value, (tuple, list)) or len(value) != 3:
            return None
        if any(item is None for item in value):
            return None
        return tuple(int(item) for item in value)

    @property
    def color_temp_kelvin(self) -> int | None:
        value = self._state("color_temp_kelvin")
        return int(value) if value is not None else None

    @property
    def color_mode(self) -> ColorMode | None:
        value = self._state("color_mode")
        if value is not None:
            try:
                return ColorMode(value)
            except ValueError:
                pass

        # HA requires a current color mode whenever color modes are exposed.
        # An adapter may intentionally omit it when the device is in a
        # preset/scene mode; keep the adapter's RGB/CCT values empty and use a
        # declared mode only to satisfy the LightEntity state contract.
        for mode in (
            ColorMode.RGB,
            ColorMode.COLOR_TEMP,
            ColorMode.BRIGHTNESS,
            ColorMode.ONOFF,
        ):
            if mode in self._attr_supported_color_modes:
                return mode
        return None

    async def async_added_to_hass(self) -> None:
        self._device_context.add_state_listener(self._state_changed)

    async def async_will_remove_from_hass(self) -> None:
        self._device_context.remove_state_listener(self._state_changed)

    async def async_turn_on(self, **kwargs: Any) -> None:
        action = self._spec.actions.get("turn_on")
        if action is None:
            return
        await action(
            self._device_context,
            {
                "brightness": kwargs.get(ATTR_BRIGHTNESS),
                "rgb_color": kwargs.get(ATTR_RGB_COLOR),
                "color_temp_kelvin": kwargs.get(ATTR_COLOR_TEMP_KELVIN),
            },
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        del kwargs
        action = self._spec.actions.get("turn_off")
        if action is not None:
            await action(self._device_context, {})

    def _state_changed(self) -> None:
        self.async_write_ha_state()

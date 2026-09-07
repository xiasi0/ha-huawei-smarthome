"""Home Assistant light projection for supported Huawei products."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .device_registry import device_identifier, profile_configuration_url


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create light entities from instantiated product devices."""

    del hass
    client = entry.runtime_data
    entities = []
    for device in client.hwiot_devices.values():
        if getattr(device, "ha_platform", None) != "light":
            continue
        light_keys = getattr(device, "light_keys", ())
        if light_keys:
            entities.extend(
                HuaweiSmartHomeLight(device, key)
                for key in light_keys
            )
        else:
            entities.append(HuaweiSmartHomeLight(device))
    async_add_entities(entities)


class HuaweiSmartHomeLight(LightEntity):
    """Project one product device as a Home Assistant light."""

    def __init__(self, device: Any, light_key: str | None = None) -> None:
        self._device = device
        self._light_key = light_key
        entity_key = light_key or getattr(device, "light_key", "light")
        light_names = getattr(device, "light_names", {})
        self._attr_unique_id = (
            f"{device.home_id}_{device.dev_id}_"
            f"{entity_key}"
        )
        self._attr_name = light_names.get(
            light_key,
            getattr(device, "light_name", "Light"),
        )
        self._attr_has_entity_name = True
        self._attr_should_poll = False
        supported_color_modes = getattr(
            device,
            "supported_color_modes",
            frozenset({"rgb", "color_temp"}),
        )
        self._attr_supported_color_modes = {
            mode
            for mode in (
                ColorMode.ONOFF,
                ColorMode.BRIGHTNESS,
                ColorMode.COLOR_TEMP,
                ColorMode.RGB,
            )
            if mode.value in supported_color_modes
        }
        self._attr_min_color_temp_kelvin = getattr(
            device, "min_color_temp_kelvin", 2000
        )
        self._attr_max_color_temp_kelvin = getattr(
            device, "max_color_temp_kelvin", 6500
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return the shared HA device identity."""

        return DeviceInfo(
            identifiers={device_identifier(self._device.descriptor)},
            name=self._device.name,
            manufacturer=self._device.manufacturer,
            model=self._device.model,
            sw_version=self._device.firmware_version,
            configuration_url=profile_configuration_url(
                self._device.prod_id,
            ),
        )

    @property
    def available(self) -> bool:
        return self._device.available

    @property
    def is_on(self) -> bool | None:
        if self._light_key is not None:
            return self._device.light_is_on(self._light_key)
        return self._device.is_on

    @property
    def brightness(self) -> int | None:
        if self._light_key is not None:
            return self._device.light_brightness(self._light_key)
        return self._device.brightness

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        if self._light_key is not None:
            return self._device.light_rgb_color(self._light_key)
        return self._device.rgb_color

    @property
    def color_temp_kelvin(self) -> int | None:
        if self._light_key is not None:
            return self._device.light_color_temperature(self._light_key)
        return self._device.color_temperature

    @property
    def color_mode(self) -> ColorMode | None:
        supported = self._attr_supported_color_modes
        if self._light_key is not None:
            colour_mode_getter = getattr(
                self._device,
                "light_colour_mode",
                None,
            )
            colour_mode = (
                colour_mode_getter(self._light_key)
                if callable(colour_mode_getter)
                else None
            )
            rgb_color = self._device.light_rgb_color(self._light_key)
            color_temperature = self._device.light_color_temperature(
                self._light_key
            )
        else:
            colour_mode = getattr(self._device, "colour_mode", None)
            rgb_color = self._device.rgb_color
            color_temperature = self._device.color_temperature
        if colour_mode == 1 and ColorMode.COLOR_TEMP in supported:
            return ColorMode.COLOR_TEMP
        if colour_mode == 0 and ColorMode.RGB in supported:
            return ColorMode.RGB
        if ColorMode.RGB in supported and rgb_color is not None:
            return ColorMode.RGB
        if (
            ColorMode.COLOR_TEMP in supported
            and color_temperature is not None
        ):
            return ColorMode.COLOR_TEMP
        if ColorMode.RGB in supported:
            return ColorMode.RGB
        if ColorMode.COLOR_TEMP in supported:
            return ColorMode.COLOR_TEMP
        if ColorMode.BRIGHTNESS in supported:
            return ColorMode.BRIGHTNESS
        if ColorMode.ONOFF in supported:
            return ColorMode.ONOFF
        return None

    async def async_added_to_hass(self) -> None:
        self._device.add_state_listener(self._state_changed)

    async def async_will_remove_from_hass(self) -> None:
        self._device.remove_state_listener(self._state_changed)

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self._light_key is not None:
            await self._device.async_turn_on_for_light(
                self._light_key,
                brightness=kwargs.get(ATTR_BRIGHTNESS),
                rgb_color=kwargs.get(ATTR_RGB_COLOR),
                color_temperature=kwargs.get(ATTR_COLOR_TEMP_KELVIN),
            )
            return
        await self._device.async_turn_on(
            brightness=kwargs.get(ATTR_BRIGHTNESS),
            rgb_color=kwargs.get(ATTR_RGB_COLOR),
            color_temperature=kwargs.get(ATTR_COLOR_TEMP_KELVIN),
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self._light_key is not None:
            del kwargs
            await self._device.async_turn_off_for_light(self._light_key)
            return
        del kwargs
        await self._device.async_turn_off()

    def _state_changed(self) -> None:
        self.async_write_ha_state()

"""Home Assistant media player projection for supported Huawei speakers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
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
    """Create media players from instantiated product devices."""

    del hass
    client = entry.runtime_data
    async_add_entities(
        HuaweiSmartHomeMediaPlayer(device)
        for device in client.hwiot_devices.values()
        if getattr(device, "ha_platform", None) == "media_player"
    )


class HuaweiSmartHomeMediaPlayer(MediaPlayerEntity):
    """Project one Huawei smart speaker as a Home Assistant media player."""

    def __init__(self, device: Any) -> None:
        self._device = device
        self._attr_unique_id = f"{device.home_id}_{device.dev_id}_media_player"
        self._attr_name = "Speaker"
        self._attr_has_entity_name = True
        self._attr_should_poll = False
        self._attr_supported_features = (
            MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.STOP
            | MediaPlayerEntityFeature.PREVIOUS_TRACK
            | MediaPlayerEntityFeature.NEXT_TRACK
            | MediaPlayerEntityFeature.VOLUME_SET
        )
        self._attr_media_content_type = "music"

    @property
    def device_info(self) -> DeviceInfo:
        """Return the shared HA device identity."""

        return DeviceInfo(
            identifiers={device_identifier(self._device.descriptor)},
            name=self._device.name,
            manufacturer=self._device.manufacturer,
            model=self._device.model,
            sw_version=self._device.firmware_version,
            configuration_url=profile_configuration_url(self._device.prod_id),
        )

    @property
    def available(self) -> bool:
        return self._device.available

    @property
    def state(self) -> MediaPlayerState | None:
        return {
            0: MediaPlayerState.PAUSED,
            1: MediaPlayerState.PLAYING,
            2: MediaPlayerState.IDLE,
        }.get(self._device.play_state)

    @property
    def volume_level(self) -> float | None:
        return self._device.volume_level

    @property
    def is_volume_muted(self) -> bool | None:
        return self._device.is_volume_muted

    @property
    def media_title(self) -> str | None:
        return _metadata_text(self._device.media_metadata, "title")

    @property
    def media_artist(self) -> str | None:
        return _metadata_text(self._device.media_metadata, "artistName")

    @property
    def media_album_name(self) -> str | None:
        return _metadata_text(self._device.media_metadata, "albumName")

    @property
    def media_image_url(self) -> str | None:
        return _metadata_text(self._device.media_metadata, "pictureUrl")

    async def async_added_to_hass(self) -> None:
        self._device.add_state_listener(self._state_changed)

    async def async_will_remove_from_hass(self) -> None:
        self._device.remove_state_listener(self._state_changed)

    async def async_media_play(self) -> None:
        await self._device.async_media_play()

    async def async_media_pause(self) -> None:
        await self._device.async_media_pause()

    async def async_media_stop(self) -> None:
        await self._device.async_media_stop()

    async def async_media_previous_track(self) -> None:
        await self._device.async_media_previous_track()

    async def async_media_next_track(self) -> None:
        await self._device.async_media_next_track()

    async def async_set_volume_level(self, volume: float) -> None:
        await self._device.async_set_volume_level(volume)

    def _state_changed(self) -> None:
        self.async_write_ha_state()


def _metadata_text(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None

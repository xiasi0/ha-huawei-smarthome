"""Generic Home Assistant media player registration for product adapters."""

from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import MediaPlayerEntity, MediaPlayerEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity_helpers import AdapterEntityMixin, iter_specs


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    del hass
    async_add_entities(HuaweiAdapterMediaPlayer(context, spec) for context, spec in iter_specs(entry.runtime_data, "media_player"))


class HuaweiAdapterMediaPlayer(AdapterEntityMixin, MediaPlayerEntity):
    def __init__(self, context: Any, spec: Any) -> None:
        self._init_adapter_entity(context, spec)
        features = MediaPlayerEntityFeature(0)
        for action, feature in (("play", MediaPlayerEntityFeature.PLAY), ("pause", MediaPlayerEntityFeature.PAUSE), ("stop", MediaPlayerEntityFeature.STOP), ("volume", MediaPlayerEntityFeature.VOLUME_SET), ("next", MediaPlayerEntityFeature.NEXT_TRACK), ("previous", MediaPlayerEntityFeature.PREVIOUS_TRACK)):
            if action in spec.actions:
                features |= feature
        self._attr_supported_features = features

    @property
    def state(self): return self._state_value("state")
    @property
    def volume_level(self): return self._state_value("volume_level")
    @property
    def is_volume_muted(self): return self._state_value("is_volume_muted")
    async def async_media_play(self): await self._run_action("play", {})
    async def async_media_pause(self): await self._run_action("pause", {})
    async def async_media_stop(self): await self._run_action("stop", {})
    async def async_set_volume_level(self, volume: float): await self._run_action("volume", {"volume": volume})
    async def async_media_next_track(self): await self._run_action("next", {})
    async def async_media_previous_track(self): await self._run_action("previous", {})

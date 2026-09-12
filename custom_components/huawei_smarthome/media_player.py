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
        for action, feature in (
            ("play", MediaPlayerEntityFeature.PLAY),
            ("pause", MediaPlayerEntityFeature.PAUSE),
            ("stop", MediaPlayerEntityFeature.STOP),
            ("volume", MediaPlayerEntityFeature.VOLUME_SET),
            ("next", MediaPlayerEntityFeature.NEXT_TRACK),
            ("previous", MediaPlayerEntityFeature.PREVIOUS_TRACK),
            ("turn_on", MediaPlayerEntityFeature.TURN_ON),
            ("turn_off", MediaPlayerEntityFeature.TURN_OFF),
            ("select_source", MediaPlayerEntityFeature.SELECT_SOURCE),
        ):
            if action in spec.actions:
                features |= feature
        self._attr_supported_features = features

    @property
    def state(self): return self._state_value("state")
    @property
    def volume_level(self): return self._state_value("volume_level")
    @property
    def is_volume_muted(self): return self._state_value("is_volume_muted")
    @property
    def media_title(self): return self._state_value("media_title")
    @property
    def media_artist(self): return self._state_value("media_artist")
    @property
    def media_album_name(self): return self._state_value("media_album_name")
    @property
    def media_image_url(self): return self._state_value("media_image_url")
    @property
    def media_series_title(self): return self._state_value("media_series_title")
    @property
    def media_season(self): return self._state_value("media_season")
    @property
    def media_episode(self): return self._state_value("media_episode")
    @property
    def media_position(self): return self._state_value("media_position")
    @property
    def media_duration(self): return self._state_value("media_duration")
    @property
    def source(self): return self._state_value("source")
    @property
    def source_list(self): return self._state_value("source_list")
    async def async_media_play(self): await self._run_action("play", {})
    async def async_media_pause(self): await self._run_action("pause", {})
    async def async_media_stop(self): await self._run_action("stop", {})
    async def async_set_volume_level(self, volume: float): await self._run_action("volume", {"volume": volume})
    async def async_media_next_track(self): await self._run_action("next", {})
    async def async_media_previous_track(self): await self._run_action("previous", {})
    async def async_turn_on(self): await self._run_action("turn_on", {})
    async def async_turn_off(self): await self._run_action("turn_off", {})
    async def async_select_source(self, source: str): await self._run_action("select_source", {"source": source})

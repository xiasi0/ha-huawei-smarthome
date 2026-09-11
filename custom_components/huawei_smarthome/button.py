"""Generic Home Assistant button registration for product adapters."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity_helpers import AdapterEntityMixin, iter_specs


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    del hass
    async_add_entities(HuaweiAdapterButton(context, spec) for context, spec in iter_specs(entry.runtime_data, "button"))


class HuaweiAdapterButton(AdapterEntityMixin, ButtonEntity):
    def __init__(self, context: Any, spec: Any) -> None:
        self._init_adapter_entity(context, spec)

    async def async_press(self) -> None:
        await self._run_action("press", {})

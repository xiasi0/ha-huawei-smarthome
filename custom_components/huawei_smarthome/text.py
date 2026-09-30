"""Generic Home Assistant text registration for product adapters."""

from __future__ import annotations

from typing import Any

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity_helpers import AdapterEntityMixin, iter_specs

# The HA frontend renders text fields with a practical length limit of 255,
# so adapters may advertise more (the Profile often allows 1024) but the
# entity never exceeds this.
_MAX_LENGTH = 255


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    del hass
    async_add_entities(
        HuaweiAdapterText(context, spec)
        for context, spec in iter_specs(entry.runtime_data, "text")
    )


class HuaweiAdapterText(AdapterEntityMixin, TextEntity):
    """A writable text field that dispatches one adapter action when set."""

    def __init__(self, context: Any, spec: Any) -> None:
        self._init_adapter_entity(context, spec)
        metadata = spec.metadata or {}
        if metadata.get("min") is not None:
            self._attr_native_min = int(metadata["min"])
        maximum = metadata.get("max")
        if maximum is not None:
            self._attr_native_max = min(int(maximum), _MAX_LENGTH)
        self._last_value: str | None = None

    def _reported_value(self) -> str | None:
        value = self._state_value("native_value")
        if isinstance(value, str) and value:
            return value
        return None

    @property
    def native_value(self) -> str | None:
        return self._reported_value() or self._last_value

    async def async_set_value(self, value: str) -> None:
        await self._run_action("set_value", {"value": value})
        # Fields that are write-only (no report) keep the typed value visible;
        # fields the device reports back will override it on the next push.
        self._last_value = value
        self.async_write_ha_state()

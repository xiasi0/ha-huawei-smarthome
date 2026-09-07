"""Home Assistant loader for the hard-coded 2OJL humidifier entity."""

from __future__ import annotations

from importlib import import_module

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the hard-coded 2OJL humidifier entity."""

    del hass
    client = entry.runtime_data
    product_module = import_module(
        ".hwiotdevices.lights.2OJL",
        package=__package__,
    )
    entity_type = product_module.create_humidifier_entity_class()
    async_add_entities(
        entity_type(device)
        for device in client.hwiot_devices.values()
        if (
            getattr(device, "ha_platform", None) == "humidifier"
            and getattr(device, "prod_id", "").strip().upper() == "2OJL"
        )
    )

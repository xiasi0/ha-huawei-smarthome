"""Home Assistant device registry entries for Huawei SmartHome."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import TYPE_CHECKING
from urllib.parse import quote

from .const import DOMAIN, MANUFACTURER, PROFILE_CDN_BASE_URL, PROFILE_CDN_PATH
from .domain.models import RemoteDeviceDescriptor

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def device_identifier(device: RemoteDeviceDescriptor) -> tuple[str, str]:
    """Return a stable HA identifier for one remote device instance."""

    return DOMAIN, device_identifier_value(device)


def device_identifier_value(device: RemoteDeviceDescriptor) -> str:
    """Return the stable identifier value used by HA and local exclusions."""

    return f"{device.home_id}:{device.dev_id}"


def profile_configuration_url(prod_id: str | None) -> str | None:
    """Build the public Product Profile URL for one product ID."""

    if not isinstance(prod_id, str) or not prod_id.strip():
        return None
    encoded = quote(prod_id.strip(), safe="")
    return (
        f"{PROFILE_CDN_BASE_URL}"
        f"{PROFILE_CDN_PATH.format(prod_id=encoded)}"
    )


def register_devices(
    hass: HomeAssistant,
    config_entry_id: str,
    devices: Iterable[RemoteDeviceDescriptor],
    *,
    excluded_device_ids: Collection[str] = (),
) -> None:
    """Create empty HA device entries without creating entities."""

    from homeassistant.helpers import device_registry as dr

    registry = dr.async_get(hass)
    for device in devices:
        if (device.node_type or "").strip().upper() == "GROUP":
            continue
        if device_identifier_value(device) in excluded_device_ids:
            continue
        registry.async_get_or_create(
            config_entry_id=config_entry_id,
            identifiers={device_identifier(device)},
            name=device.name,
            manufacturer=device.manufacturer or MANUFACTURER,
            model=device.model or device.prod_id or device.device_type_id,
            sw_version=device.firmware_version,
            configuration_url=profile_configuration_url(device.prod_id),
        )

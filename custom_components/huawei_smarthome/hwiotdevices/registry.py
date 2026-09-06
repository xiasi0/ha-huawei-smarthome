"""Route discovered products to their explicit device implementation."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from ..domain.models import RemoteDeviceDescriptor
from ..mqtt_client import HuaweiMqttClient


_SUPPORTED_PRODUCTS = {
    "108t": import_module(".hvac.108T", package=__package__).HuaweiDevice,
    "100z": import_module(".lights.100z", package=__package__).HuaweiDevice,
    "105m": import_module(".electrical.105M", package=__package__).HuaweiDevice,
    "2mff": import_module(".electrical.2MFF", package=__package__).HuaweiDevice,
    "2bn0": import_module(".electrical.2BN0", package=__package__).HuaweiDevice,
    "124u": import_module(".electrical.124U", package=__package__).HuaweiDevice,
    "148m": import_module(".electrical.148M", package=__package__).HuaweiDevice,
    "20hz": import_module(".lights.20HZ", package=__package__).HuaweiDevice,
    "2f6r": import_module(".lights.2F6R", package=__package__).HuaweiDevice,
    "2kj0": import_module(".lights.2KJ0", package=__package__).HuaweiDevice,
    "2oib": import_module(".lights.2OIB", package=__package__).HuaweiDevice,
    "2i7c": import_module(".lights.2I7C", package=__package__).HuaweiDevice,
    "2i7k": import_module(".lights.2I7K", package=__package__).HuaweiDevice,
    "2rjb": import_module(".security.2RJB", package=__package__).HuaweiDevice,
    "zg0f": import_module(".security.ZG0F", package=__package__).HuaweiDevice,
    "zg1y": import_module(".security.ZG1Y", package=__package__).HuaweiDevice,
}


def create_hwiot_device(
    descriptor: RemoteDeviceDescriptor,
    mqtt: HuaweiMqttClient,
) -> Any | None:
    """Create the supported product object for one device."""

    if (descriptor.node_type or "").strip().upper() == "GROUP":
        return None
    product_id = (descriptor.prod_id or "").strip().lower()
    device_type = _SUPPORTED_PRODUCTS.get(product_id)
    if device_type is None:
        return None
    return device_type(descriptor, mqtt)

"""Route discovered products to their explicit device implementation."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from ..domain.models import RemoteDeviceDescriptor
from ..mqtt_client import HuaweiMqttClient


_SUPPORTED_PRODUCTS = {
    "100z": import_module(".lights.100z", package=__package__).HuaweiDevice,
    "20hz": import_module(".lights.20HZ", package=__package__).HuaweiDevice,
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

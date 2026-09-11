"""User-contributed protocol for Huawei product 113C."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


def _field(
    profile: Mapping[str, Any],
    sid: str,
    name: str,
) -> Mapping[str, Any] | None:
    for service in profile.get("services", ()):
        if not isinstance(service, Mapping) or service.get("serviceId") != sid:
            continue
        for field in service.get("characteristics", ()):
            if (
                isinstance(field, Mapping)
                and field.get("characteristicName") == name
            ):
                return field
    return None


def _is_on(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.casefold() in {"1", "true", "on"}:
            return True
        if value.casefold() in {"0", "false", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


class Product113cAdapter:
    """Project the 113C motion and low-battery services."""

    prod_id = "113C"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        entities: list[EntitySpec] = []
        if context.has_service("motionSensor") and _field(
            profile,
            "motionSensor",
            "alarm",
        ) is not None:

            def motion_state(device: DeviceContext) -> Mapping[str, Any]:
                return {"is_on": _is_on(device.value("motionSensor", "alarm"))}

            entities.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="motion",
                    name="移动探测",
                    state=motion_state,
                    metadata={"device_class": "motion"},
                )
            )

        if context.has_service("battery") and _field(
            profile,
            "battery",
            "lowBattery",
        ) is not None:

            def low_battery_state(device: DeviceContext) -> Mapping[str, Any]:
                return {"is_on": _is_on(device.value("battery", "lowBattery"))}

            entities.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="low_battery",
                    name="低电量",
                    state=low_battery_state,
                    metadata={"device_class": "battery"},
                )
            )

        return tuple(entities)


ADAPTER = Product113cAdapter()

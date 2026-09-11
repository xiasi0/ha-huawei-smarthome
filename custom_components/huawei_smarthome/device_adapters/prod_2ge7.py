"""User-contributed protocol for Huawei product 2GE7.

Device: 麦乐克 门窗传感器 / MicLeck door contact sensor (deviceModel
``MIR-MC100``, manufacturer ``麦乐克``, protocolType ``Mesh``).
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/2GE7/2GE7.json

This device is strictly read-only: the Profile declares no writable
characteristic outside ``update.action`` (OTA, not exposed), and the vendor H5
bundle's only ``setDeviceInfo`` call lives in the shared ``LampBanner1``
template whose switch card is disabled for this product (``"hasswitch":
false`` in ``data/index.data.js``).

Exposed entities (all read-only):

* ``binary_sensor`` "门窗"        <- ``doorContact.status`` (0 关闭 / 1 打开,
                                    device_class ``door``)
* ``sensor`` "电池电量"           <- ``battery.level`` (0..100 %)
* ``binary_sensor`` "低电量告警"  <- ``battery.alarm`` (device_class
                                    ``battery``; vendor card labels 无告警 /
                                    低电量告警)
* ``binary_sensor`` "故障"        <- ``commonFaultDetection.status``
                                    (device_class ``problem``)
* ``sensor`` "故障码"             <- ``commonFaultDetection.code``, text
                                    labels from the Profile (0 正常 /
                                    1 低压故障 / 2 设备被拆除); unknown
                                    values map to unknown, never guessed

Deliberately *not* exposed:

* ``netInfo`` / ``update`` — read-only diagnostics and OTA, consistent with
  the other sensor adapters.
* ``switch`` — the Profile has no switch service; the ``setDeviceInfo``
  dispatch in the H5 is dead template code for this product.

Unknown enum values return ``None`` so HA shows unknown instead of a wrong
label.  This adapter was derived from the Profile and vendor H5 bundle and is
not yet verified on a physical device.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_DOOR_SID = "doorContact"
_DOOR_FIELD = "status"

_BATTERY_SID = "battery"
_BATTERY_LEVEL_FIELD = "level"
_BATTERY_ALARM_FIELD = "alarm"

_FAULT_SID = "commonFaultDetection"
_FAULT_STATUS_FIELD = "status"
_FAULT_CODE_FIELD = "code"

# Labels come from the Profile's enumList descriptions (authoritative).
_DOOR_IS_ON_VALUE = 1  # 1 打开 -> binary_sensor on; 0 关闭 -> off
_FAULT_CODE_OPTIONS: tuple[tuple[int, str], ...] = (
    (0, "正常"),
    (1, "低压故障"),
    (2, "设备被拆除"),
)


def _service(profile: Mapping[str, Any], sid: str) -> Mapping[str, Any] | None:
    for service in profile.get("services", ()):
        if isinstance(service, Mapping) and service.get("serviceId") == sid:
            return service
    return None


def _field(
    profile: Mapping[str, Any],
    sid: str,
    name: str,
) -> Mapping[str, Any] | None:
    service = _service(profile, sid)
    if service is None:
        return None
    for field in service.get("characteristics", ()):
        if isinstance(field, Mapping) and field.get("characteristicName") == name:
            return field
    return None


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.strip().casefold() in {"1", "true", "on"}:
            return True
        if value.strip().casefold() in {"0", "false", "off"}:
            return False
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _enum_label(
    value: Any,
    options: tuple[tuple[int, str], ...],
) -> str | None:
    number = _number(value)
    if number is None:
        return None
    for enum_value, label in options:
        if number == enum_value:
            return label
    return None


class Product2ge7Adapter:
    """Keep all 2GE7 entity choices in this file."""

    prod_id = "2GE7"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        specs: list[EntitySpec] = []

        # --- door contact (read-only) --------------------------------------
        if context.has_service(_DOOR_SID) and _field(
            profile, _DOOR_SID, _DOOR_FIELD
        ) is not None:
            def door_state(device: DeviceContext) -> Mapping[str, Any]:
                # The device only reports 0 关闭 / 1 打开; anything else is
                # unknown rather than a guessed state.
                value = _number(device.value(_DOOR_SID, _DOOR_FIELD))
                if value not in (0, 1):
                    return {"is_on": None}
                return {"is_on": value == _DOOR_IS_ON_VALUE}

            specs.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="door",
                    name="门窗",
                    state=door_state,
                    metadata={"device_class": "door"},
                )
            )

        # --- battery (read-only) -------------------------------------------
        if context.has_service(_BATTERY_SID):
            if _field(profile, _BATTERY_SID, _BATTERY_LEVEL_FIELD) is not None:
                def battery_state(device: DeviceContext) -> Mapping[str, Any]:
                    return {
                        "native_value": _number(
                            device.value(_BATTERY_SID, _BATTERY_LEVEL_FIELD)
                        )
                    }

                specs.append(
                    EntitySpec(
                        platform="sensor",
                        key="battery_level",
                        name="电池电量",
                        state=battery_state,
                        metadata={
                            "device_class": "battery",
                            "state_class": "measurement",
                            "unit": "%",
                        },
                    )
                )
            if _field(profile, _BATTERY_SID, _BATTERY_ALARM_FIELD) is not None:
                def alarm_state(device: DeviceContext) -> Mapping[str, Any]:
                    return {
                        "is_on": _bool(
                            device.value(_BATTERY_SID, _BATTERY_ALARM_FIELD)
                        )
                    }

                specs.append(
                    EntitySpec(
                        platform="binary_sensor",
                        key="battery_alarm",
                        name="低电量告警",
                        state=alarm_state,
                        metadata={"device_class": "battery"},
                    )
                )

        # --- fault (read-only) ----------------------------------------------
        if context.has_service(_FAULT_SID):
            if _field(profile, _FAULT_SID, _FAULT_STATUS_FIELD) is not None:
                def fault_state(device: DeviceContext) -> Mapping[str, Any]:
                    return {
                        "is_on": _bool(
                            device.value(_FAULT_SID, _FAULT_STATUS_FIELD)
                        )
                    }

                specs.append(
                    EntitySpec(
                        platform="binary_sensor",
                        key="fault",
                        name="故障",
                        state=fault_state,
                        metadata={"device_class": "problem"},
                    )
                )
            if _field(profile, _FAULT_SID, _FAULT_CODE_FIELD) is not None:
                def fault_code_state(device: DeviceContext) -> Mapping[str, Any]:
                    return {
                        "native_value": _enum_label(
                            device.value(_FAULT_SID, _FAULT_CODE_FIELD),
                            _FAULT_CODE_OPTIONS,
                        )
                    }

                specs.append(
                    EntitySpec(
                        platform="sensor",
                        key="fault_code",
                        name="故障码",
                        state=fault_code_state,
                    )
                )

        return tuple(specs)


ADAPTER = Product2ge7Adapter()

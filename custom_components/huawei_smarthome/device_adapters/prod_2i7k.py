"""User-contributed protocol for Huawei product 2I7K (OPPLE lighting drive).

Profile: switch.on / brightness.brightness (1..100%) / cct.colorTemperature
(2700..5700) / commonFaultDetection.{code,status} / netInfo diagnostics.

H5 evidence (h5_001/js/index.js, template-style unminified bundle):
- LampBanner1.onCardClick  -> setDeviceInfo({switch: {on: Number(e)}})
- LampBrightness1.ontouchend -> setDeviceInfo({brightness: {brightness: Number(e)}})
- LampCCT1.ontouchend -> setDeviceInfo({cct: {colorTemperature: Number(e)}})
- colourMode only ever appears in updateUI() and has no Profile service -> ignored.
- toggleSwitch ("开关翻转") is rendered as a GeneralCard with disabled:true and
  has no event handler anywhere in the bundle (no setDeviceInfo reference) ->
  no entity is exposed for it (宁可不出).
- The update service has no UI in this bundle (sdk.js setDeviceInfo call sites
  only cover timer / progressTurnOff template leftovers that are absent from
  this Profile) -> no button is exposed for it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


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
        if value.casefold() in {"1", "true", "on"}:
            return True
        if value.casefold() in {"0", "false", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        return value or None
    return str(value)


def _profile_range(field: Mapping[str, Any]) -> tuple[float, float] | None:
    minimum = _number(field.get("min"))
    maximum = _number(field.get("max"))
    if minimum is None or maximum is None or maximum <= minimum:
        return None
    return float(minimum), float(maximum)


def _clamp(value: Any, field: Mapping[str, Any]) -> int | float | None:
    number = _number(value)
    value_range = _profile_range(field)
    if number is None or value_range is None:
        return number
    minimum, maximum = value_range
    number = min(max(float(number), minimum), maximum)
    return int(number) if number.is_integer() else number


def _device_brightness_to_ha(
    value: Any,
    field: Mapping[str, Any],
) -> int | None:
    """Convert the product's 1..100% brightness to HA's 1..255 scale.

    HA treats brightness 0 as "off", so the device's minimum level maps to
    HA brightness 1 instead of 0 (otherwise the lowest step would collapse
    into "off").
    """
    number = _number(value)
    value_range = _profile_range(field)
    if number is None or value_range is None:
        return None
    minimum, maximum = value_range
    number = min(max(float(number), minimum), maximum)
    return round(1 + (number - minimum) * 254 / (maximum - minimum))


def _ha_brightness_to_device(
    value: Any,
    field: Mapping[str, Any],
) -> int | float:
    """Convert HA's 1..255 brightness back to the product Profile range."""

    number = _number(value)
    value_range = _profile_range(field)
    if number is None or value_range is None:
        raise ValueError("2I7K brightness range is missing from the Profile")
    minimum, maximum = value_range
    number = min(max(float(number), 1.0), 255.0)
    device_value = minimum + (number - 1.0) * (maximum - minimum) / 254.0
    if (field.get("characteristicType") or "").casefold() in {"int", "integer"}:
        return int(round(device_value))
    return device_value


def _enum_labels(field: Mapping[str, Any]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for option in field.get("enumList", ()) or ():
        if not isinstance(option, Mapping):
            continue
        key = option.get("enumVal")
        if key is None:
            continue
        labels[str(key)] = str(option.get("descCh") or option.get("enumVal"))
    return labels


def _enum_text(field: Mapping[str, Any], value: Any) -> str | None:
    """Map a raw characteristic value to its Profile enum label.

    Unknown values return None (unknown) instead of guessing a label.
    """
    if value is None or isinstance(value, bool):
        return None
    number = _number(value)
    key = str(int(number)) if number is not None else str(value)
    return _enum_labels(field).get(key)


async def _turn_on(context: DeviceContext, data: Mapping[str, Any]) -> None:
    profile = context.profile or {}
    await context.async_send_service("switch", {"on": 1})
    if data.get("brightness") is not None:
        brightness_field = _field(profile, "brightness", "brightness")
        if brightness_field is None:
            raise ValueError("2I7K brightness field is missing from the Profile")
        await context.async_send_service(
            "brightness",
            {
                "brightness": _ha_brightness_to_device(
                    data["brightness"],
                    brightness_field,
                )
            },
        )
    if data.get("color_temp_kelvin") is not None:
        cct_field = _field(profile, "cct", "colorTemperature")
        if cct_field is None:
            raise ValueError("2I7K cct field is missing from the Profile")
        temperature = _clamp(data["color_temp_kelvin"], cct_field)
        if temperature is not None:
            await context.async_send_service(
                "cct",
                {"colorTemperature": temperature},
            )


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 0})


class Product2I7KAdapter:
    prod_id = "2I7K"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None or not context.has_service("switch"):
            return ()
        if _field(profile, "switch", "on") is None:
            return ()

        entities: list[EntitySpec] = []
        entities.extend(self._light_entities(context, profile))
        entities.extend(self._fault_entities(context, profile))
        entities.extend(self._net_info_entities(context, profile))
        return tuple(entities)

    def _light_entities(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        brightness_field = _field(profile, "brightness", "brightness")
        cct_field = _field(profile, "cct", "colorTemperature")

        supported_modes: set[str] = set()
        if cct_field is not None and _profile_range(cct_field) is not None:
            supported_modes.add("color_temp")
        if brightness_field is not None and _profile_range(brightness_field) is not None:
            supported_modes.add("brightness")
        if not supported_modes:
            supported_modes.add("onoff")

        def light_state(device: DeviceContext) -> Mapping[str, Any]:
            state: dict[str, Any] = {
                "is_on": _bool(device.value("switch", "on")),
                "brightness": None,
                "color_temp_kelvin": None,
                "color_mode": (
                    "color_temp"
                    if "color_temp" in supported_modes
                    else ("brightness" if "brightness" in supported_modes else "onoff")
                ),
            }
            if "brightness" in supported_modes:
                state["brightness"] = _device_brightness_to_ha(
                    device.value("brightness", "brightness"),
                    brightness_field or {},
                )
            if "color_temp" in supported_modes:
                state["color_temp_kelvin"] = _number(
                    device.value("cct", "colorTemperature")
                )
            return state

        metadata: dict[str, Any] = {"supported_color_modes": supported_modes}
        if "color_temp" in supported_modes:
            metadata["min_color_temp_kelvin"] = (cct_field or {}).get("min")
            metadata["max_color_temp_kelvin"] = (cct_field or {}).get("max")

        return (
            EntitySpec(
                platform="light",
                key="light",
                name=None,
                state=light_state,
                metadata=metadata,
                actions={"turn_on": _turn_on, "turn_off": _turn_off},
            ),
        )

    def _fault_entities(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        entities: list[EntitySpec] = []
        if context.has_service("commonFaultDetection"):
            code_field = _field(profile, "commonFaultDetection", "code")
            if code_field is not None:

                def fault_state(device: DeviceContext) -> Mapping[str, Any]:
                    return {
                        "native_value": _enum_text(
                            code_field,
                            device.value("commonFaultDetection", "code"),
                        )
                    }

                entities.append(
                    EntitySpec(
                        platform="sensor",
                        key="fault_status",
                        name="故障状态",
                        state=fault_state,
                        metadata={},
                    )
                )

            status_field = _field(profile, "commonFaultDetection", "status")
            if status_field is not None:

                def problem_state(device: DeviceContext) -> Mapping[str, Any]:
                    # Profile enum: 1=设备运行异常, 0=运行正常
                    status = _number(device.value("commonFaultDetection", "status"))
                    return {"is_on": None if status is None else status == 1}

                entities.append(
                    EntitySpec(
                        platform="binary_sensor",
                        key="fault_problem",
                        name="故障告警",
                        state=problem_state,
                        metadata={"device_class": "problem"},
                    )
                )
        return tuple(entities)

    def _net_info_entities(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        if not context.has_service("netInfo"):
            return ()

        entities: list[EntitySpec] = []

        rssi_field = _field(profile, "netInfo", "RSSI")
        if rssi_field is not None:

            def rssi_state(device: DeviceContext) -> Mapping[str, Any]:
                return {"native_value": _number(device.value("netInfo", "RSSI"))}

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="wifi_rssi",
                    name="信号强度",
                    state=rssi_state,
                    metadata={
                        "unit": rssi_field.get("unit"),
                        "state_class": "measurement",
                    },
                )
            )

        intensity_field = _field(profile, "netInfo", "intensity")
        if intensity_field is not None:

            def intensity_state(device: DeviceContext) -> Mapping[str, Any]:
                # Profile enum: 20/40/60/80/100 -> 0..4 格信号
                return {
                    "native_value": _enum_text(
                        intensity_field,
                        device.value("netInfo", "intensity"),
                    )
                }

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="wifi_level",
                    name="信号等级",
                    state=intensity_state,
                    metadata={},
                )
            )

        for char_name, key, label in (
            ("SSID", "wifi_ssid", "Wi-Fi 名称"),
            ("IP", "wifi_ip", "IP 地址"),
            ("BSSID", "wifi_bssid", "BSSID"),
        ):
            if _field(profile, "netInfo", char_name) is None:
                continue

            def text_state(device: DeviceContext, name: str = char_name) -> Mapping[str, Any]:
                return {"native_value": _text(device.value("netInfo", name))}

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key=key,
                    name=label,
                    state=text_state,
                    metadata={},
                )
            )

        return tuple(entities)


ADAPTER = Product2I7KAdapter()

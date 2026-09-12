"""User-contributed protocol for Huawei product 2O8R (spot lamp).

Profile: switch.on / brightness.brightness (1..100%) /
cct.colorTemperature (2700..6500) / lightMode.mode (enum 0..4) /
fadeTime.value (string, seconds) / timer + delay (CRUD) / ota / netInfo.

H5 evidence (h5_001, webpack bundle: js/app.980747b9.js + async chunk
js/592.d06cfc0a.js):
- switch toggle -> setDevInfo({switch: {on: t}})
- light mode buttons (btnList2): mode 0=会客 (lang.visitor), 1=休闲
  (lang.lifeRlax), 2=阅读 (lang.redemode), 3=观影 (lang.mvemode);
  dispatched via btnClick -> setDevInfo({lightMode: {mode: t}}).
  Mode 4 (Profile descCh "自由态") has no button and is never sent in the
  whole bundle -- it is the device-side "custom" state after manual slider
  adjustments. It stays in the select options (the device can report it);
  its label comes from the Profile since the H5 has none.
- brightness slider min:1 max:100 step:1 -> setDevInfo({brightness:
  {brightness: t}})
- cct slider min:2700 max:6500 step:1 -> setDevInfo({cct:
  {colorTemperature: t}})
- gradient duration picker (customPickeOptionInt) offers 0..10 seconds,
  0 = 关闭 (lang.closedStr); customPickeCnfirm -> setDevInfo({fadeTime:
  {value: e}}) where e is a STRING ("0".."10", Profile type string).
- timer/delay pages are native (window.hilink.jumpTo(
  "com.huawei.smarthome.timerPage")) -- CRUD protocol only, no persistent
  entities exposed (宁可不出).
- The ota/update service has no UI anywhere in the bundle -> no entity.
- netInfo is not rendered in the H5; sensors follow the Profile enums
  (same treatment as 2I7K).
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
        raise ValueError("2O8R brightness range is missing from the Profile")
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


def _enum_payload(value: str, field: Mapping[str, Any]) -> Any:
    """Convert a selected label back to the wire value.

    Numeric enum values are sent as ints, non-numeric ones verbatim.
    """
    labels = _enum_labels(field)
    for key, label in labels.items():
        if label == value:
            try:
                return int(float(key))
            except (TypeError, ValueError):
                return key
    return None


async def _turn_on(context: DeviceContext, data: Mapping[str, Any]) -> None:
    profile = context.profile or {}
    await context.async_send_service("switch", {"on": 1})
    if data.get("brightness") is not None:
        brightness_field = _field(profile, "brightness", "brightness")
        if brightness_field is None:
            raise ValueError("2O8R brightness field is missing from the Profile")
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
            raise ValueError("2O8R cct field is missing from the Profile")
        temperature = _clamp(data["color_temp_kelvin"], cct_field)
        if temperature is not None:
            await context.async_send_service(
                "cct",
                {"colorTemperature": temperature},
            )


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 0})


# H5 labels (app.js lang pack): visitor=会客, lifeRlax=休闲, redemode=阅读,
# mvemode=观影. Mode 4 only exists in the Profile ("自由态") -- the H5 never
# renders or sends it.
_MODE_LABELS = {"0": "会客", "1": "休闲", "2": "阅读", "3": "观影", "4": "自由态"}

# H5 gradient picker (customPickeOptionInt): 0..10 seconds, 0 = 关闭.
_FADE_TIME_MIN = 0.0
_FADE_TIME_MAX = 10.0


class Product2O8RAdapter:
    prod_id = "2O8R"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None or not context.has_service("switch"):
            return ()
        if _field(profile, "switch", "on") is None:
            return ()

        entities: list[EntitySpec] = []
        entities.extend(self._light_entities(context, profile))
        entities.extend(self._mode_entities(context, profile))
        entities.extend(self._fade_time_entities(context, profile))
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

    def _mode_entities(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        mode_field = _field(profile, "lightMode", "mode")
        if mode_field is None:
            return ()

        # Profile enum labels override nothing here: the first four labels
        # match the H5 lang pack; mode 4 only exists in the Profile and is
        # kept so the device can report it.
        labels = dict(_MODE_LABELS)
        for key, label in _enum_labels(mode_field).items():
            labels.setdefault(key, label)
        options = tuple(
            labels[key] for key in sorted(labels, key=lambda k: int(k) if k.isdigit() else 0)
        )
        if len(set(options)) != len(options):
            # Profile/H5 label collision (should not happen): fall back to
            # raw values for the duplicates' safety.
            options = tuple(f"{labels[k]} ({k})" for k in sorted(labels))

        def mode_state(device: DeviceContext) -> Mapping[str, Any]:
            value = device.value("lightMode", "mode")
            if value is None:
                return {"current_option": None}
            number = _number(value)
            key = str(int(number)) if number is not None else str(value)
            return {"current_option": labels.get(key)}

        async def select_option(
            device: DeviceContext,
            data: Mapping[str, Any],
        ) -> None:
            payload = _enum_payload(data.get("option") or "", mode_field)
            if payload is None:
                raise ValueError(
                    f"2O8R unknown lightMode option: {data.get('option')!r}"
                )
            await device.async_send_service("lightMode", {"mode": payload})

        return (
            EntitySpec(
                platform="select",
                key="light_mode",
                name="灯光模式",
                state=mode_state,
                metadata={"options": options},
                actions={"select_option": select_option},
            ),
        )

    def _fade_time_entities(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        if _field(profile, "fadeTime", "value") is None:
            return ()

        def fade_state(device: DeviceContext) -> Mapping[str, Any]:
            # Device reports a string ("0".."10"); unknown/empty -> None.
            return {
                "native_value": _number(device.value("fadeTime", "value"))
            }

        async def set_value(device: DeviceContext, data: Mapping[str, Any]) -> None:
            number = _number(data.get("value"))
            if number is None:
                raise ValueError(f"2O8R invalid fadeTime value: {data.get('value')!r}")
            clamped = min(max(float(number), _FADE_TIME_MIN), _FADE_TIME_MAX)
            # H5 sends a string ("0".."10"), Profile type is string.
            await device.async_send_service(
                "fadeTime",
                {"value": str(int(clamped))},
            )

        return (
            EntitySpec(
                platform="number",
                key="fade_time",
                name="渐变时长",
                state=fade_state,
                metadata={
                    "min": _FADE_TIME_MIN,
                    "max": _FADE_TIME_MAX,
                    "step": 1,
                    # H5 appends lang.secondsLow ("秒") to the value.
                    "unit": "s",
                },
                actions={"set_value": set_value},
            ),
        )

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


ADAPTER = Product2O8RAdapter()

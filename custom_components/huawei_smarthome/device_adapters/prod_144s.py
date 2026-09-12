"""User-contributed protocol for Huawei product 144S (杜亚智能卷帘 DM35, WiFi).

Profile: opener.{current R, target RW} 0..100% / schedule.{enable, num,
week, action(1=update/2=delete), timer array} / update (OTA) / netInfo.

H5 evidence (h5_001, old webpack "对开帘国际化" bundle, everything in app.js):
- position slider touchend (setLevel): setDeviceInfo({opener:{target: N}})
  where N = ceil(distance/width*100) — the device value is a plain 0..100
  开合度 with no mirroring (unlike the 2MDV canvas transform).
- quick buttons (btnclick): setTarget with 0=全关 / 50=半开 / 100=全开
  (i18n: closeAll/openHalf/openAll; openLevel=开合度).
- report path (getDevCacheAllResult -> setData/setData1): opener.data.current
  is the physical position, opener.data.target the last commanded target.
  i18n curtainOpen/curtainClose confirm 100=全开 / 0=全关.

Not exposed (宁可不出):
- schedule: the H5 implements full timer CRUD, but EVERY dispatch sends the
  complete schedule object ({schedule:{enable,num,week,action,timer:[...]}})
  built from the cached state; partial payloads (e.g. only {enable}) are
  unproven, and CRUD of the timer array does not map to simple HA entities.
- update: OTA service declared in the Profile but zero UI dispatch sites.
- mode: the bundle's built-in validation schema mentions sid:"mode" (family
  leftovers from 对开帘 siblings), but the 144S Profile has no such service
  and there is no send evidence.
- cover stop: no 停止/暂停 anywhere in the bundle — stop is simply not
  supported by this target-only protocol.
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


def _clamp_to_profile(value: Any, field: Mapping[str, Any]) -> int | float | None:
    number = _number(value)
    value_range = _profile_range(field)
    if number is None or value_range is None:
        return number
    minimum, maximum = value_range
    number = min(max(float(number), minimum), maximum)
    return int(number) if number.is_integer() else number


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
    """Map a raw characteristic value to its Profile enum label."""
    if value is None or isinstance(value, bool):
        return None
    try:
        key = str(int(float(value)))
    except (TypeError, ValueError):
        key = _text(value)
    return _enum_labels(field).get(key or "")


class Product144SAdapter:
    prod_id = "144S"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()
        entities: list[EntitySpec] = []
        entities.extend(self._cover_entity(context, profile))
        entities.extend(self._net_info_entities(context, profile))
        return tuple(entities)

    def _cover_entity(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        if not context.has_service("opener"):
            return ()
        target_field = _field(profile, "opener", "target")
        if target_field is None:
            return ()

        def cover_state(device: DeviceContext) -> Mapping[str, Any]:
            position = _number(device.value("opener", "current"))
            return {
                "current_position": position,
                # H5 i18n: 100=全开, 0=全关
                "is_closed": None if position is None else position == 0,
            }

        async def set_position(context: DeviceContext, data: Mapping[str, Any]) -> None:
            clamped = _clamp_to_profile(data.get("position"), target_field)
            if clamped is None:
                raise ValueError(f"144S invalid curtain position: {data.get('position')!r}")
            await context.async_send_service("opener", {"target": clamped})

        async def open_cover(context: DeviceContext, _data: Mapping[str, Any]) -> None:
            await context.async_send_service("opener", {"target": 100})

        async def close_cover(context: DeviceContext, _data: Mapping[str, Any]) -> None:
            await context.async_send_service("opener", {"target": 0})

        return (
            EntitySpec(
                platform="cover",
                key="curtain",
                name=None,
                state=cover_state,
                metadata={},
                actions={
                    "open": open_cover,
                    "close": close_cover,
                    "set_position": set_position,
                },
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
                    metadata={"state_class": "measurement"},
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


ADAPTER = Product144SAdapter()

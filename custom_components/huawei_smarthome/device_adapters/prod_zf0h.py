"""Product adapter for the HUAWEI Home Panel S2 (ZF0H, 华为全屋智能 智能中控屏 S2).

Profile: 21 services — ``communication`` (播报指定文字) / ``speakerIfttt``
(播报指定内容) / ``panelStatus`` / ``battery`` / ``volSwitch`` /
``undisturbMode`` / ``deviceInfo`` / ``discovery`` / ``devList`` /
``addDevice`` / ``netInfo`` / ``panelMode`` / ``recoverConfigSwitch`` /
``blueBroadcast`` / ``assistant`` / ``micSwitch`` / ``logReport`` / ``update``
/ ``faceEntryAuthorization`` / ``cameraSwitch`` / ``homeBroadcast``.

H5 evidence (h5_001 "中控屏设置" bundle, 19 ``setDeviceInfo`` dispatch sites):

Exposed:

* ``switch`` "静音" <- ``volSwitch.on`` — the bundle dispatches
  ``{volSwitch:{on:0|1}}``.
* ``switch`` "勿扰模式" <- ``undisturbMode.on`` — the bundle dispatches
  ``{undisturbMode:{on,start,end}}``.  ``start``/``end`` are ``HHMMSS`` strings;
  they are surfaced read-only on the companion "勿扰时段" diagnostic sensor.
* ``select`` "面板模式" <- ``panelMode.extendMode`` — the bundle dispatches
  ``{panelMode:{extendMode:0|10001}}``; 0 = 标准模式, 10001 = 酒店模式 (the card
  is gated behind ``supportHotelMode``).
* ``sensor`` diagnostics: ``battery.level`` (电量) / ``panelStatus.status``
  (摆放状态) / ``netInfo.RSSI`` (Wi-Fi 信号) / ``update.version`` (固件版本) /
  ``devList.devList`` (已扫描子设备).
* ``text`` broadcast fields — "语音播报" <- ``communication.directive``,
  "家庭广播" <- ``homeBroadcast.text``, "播报室温内容" <-
  ``speakerIfttt.reportRoomTemp`` and "播报天气内容" <-
  ``speakerIfttt.reportWeather``.  These require the framework's ``text``
  platform (see ``text.py`` / ``PLATFORMS``).

Deliberately *not* exposed (宁可不出):

* ``micSwitch`` / ``cameraSwitch`` / ``faceEntryAuthorization`` / ``discovery``
  / ``recoverConfigSwitch`` — the Profile marks them writable (RW), but the H5
  bundle contains ZERO ``setDeviceInfo`` dispatch sites for them, so their write
  semantics are unverified.
* ``communication.directive`` / ``homeBroadcast.text`` / ``speakerIfttt.*`` are
  exposed as text despite the same lack of dispatch sites, because the Profile
  clearly describes them as string broadcasts; this mapping is derived from the
  Profile and is NOT verified on a device (writing may merely store a value
  instead of playing audio).
* ``addDevice`` (needs a runtime device list), ``blueBroadcast`` (needs a target
  MAC), ``logReport`` (internal diagnostics), ``assistant`` (cloud rule
  semantics), ``update.action`` (fires OTA), ``deviceInfo.id`` (opaque id).

Also note: the bundle dispatches a few services (``ringLightSwitch``,
``extendMenuSwitch``, ``backupInd``, voice-assistant mode) that are NOT present
in this prodId's Profile, so no entity can be built for them here.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from .api import EntitySpec
from .context import DeviceContext

_COMM_OK, _COMM_ERR = 1, 0


def _service(profile: Any, sid: str) -> Any:
    if profile is None:
        return None
    for service in profile.get("services", ()):
        if service.get("serviceId") == sid:
            return service
    return None


def _field(profile: Any, sid: str, name: str) -> Mapping[str, Any] | None:
    service = _service(profile, sid)
    if service is None:
        return None
    for characteristic in service.get("characteristics", ()):
        if characteristic.get("characteristicName") == name:
            return characteristic
    return None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    try:
        return bool(int(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        return value or None
    return str(value)


def _enum_text(context: DeviceContext, sid: str, name: str) -> str | None:
    raw = context.value(sid, name)
    if raw is None or isinstance(raw, bool):
        return None
    try:
        key = str(int(str(raw).strip()))
    except (TypeError, ValueError):
        return _text(raw)
    field = _field(context.profile, sid, name)
    if field is None:
        return None
    for option in field.get("enumList", ()) or ():
        if str(option.get("enumVal")) == key:
            return str(option.get("descCh") or option.get("enumVal"))
    return None


def _clock(value: Any) -> str | None:
    """``"230000"`` -> ``"23:00"``; anything else is returned as-is."""
    text = _text(value)
    if text and len(text) == 6 and text.isdigit():
        return f"{text[0:2]}:{text[2:4]}"
    return text


def _switch_spec(sid: str, field: str, key: str, name: str) -> EntitySpec:
    async def _turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        await context.async_send_service(sid, {field: _COMM_OK})

    async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
        await context.async_send_service(sid, {field: _COMM_ERR})

    return EntitySpec(
        platform="switch",
        key=key,
        name=name,
        state=lambda ctx, _s=sid, _f=field: {"is_on": _bool(ctx.value(_s, _f))},
        actions={"turn_on": _turn_on, "turn_off": _turn_off},
    )


def _text_spec(sid: str, field: str, key: str, name: str, maximum: int) -> EntitySpec:
    async def _set_value(context: DeviceContext, data: Mapping[str, Any]) -> None:
        await context.async_send_service(sid, {field: str(data.get("value", ""))})

    return EntitySpec(
        platform="text",
        key=key,
        name=name,
        state=lambda ctx, _s=sid, _f=field: {
            "native_value": _text(ctx.value(_s, _f))
        },
        metadata={"min": 0, "max": maximum},
        actions={"set_value": _set_value},
    )


_PANEL_MODE_LABELS = {0: "标准模式", 10001: "酒店模式"}


def _panel_mode_option(context: DeviceContext) -> str | None:
    raw = context.value("panelMode", "extendMode")
    try:
        return _PANEL_MODE_LABELS.get(int(str(raw).strip()))
    except (TypeError, ValueError):
        return None


async def _select_panel_mode(context: DeviceContext, data: Mapping[str, Any]) -> None:
    option = data.get("option")
    for raw, label in _PANEL_MODE_LABELS.items():
        if label == option:
            await context.async_send_service("panelMode", {"extendMode": raw})
            return


def _undisturb_range(context: DeviceContext) -> dict[str, Any]:
    start = _clock(context.value("undisturbMode", "start"))
    end = _clock(context.value("undisturbMode", "end"))
    if not start and not end:
        return {"native_value": None}
    return {
        "native_value": f"{start or '--'}~{end or '--'}",
        "extra_state_attributes": {"start": start, "end": end},
    }


def _device_count(context: DeviceContext) -> dict[str, Any]:
    raw = context.value("devList", "devList")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return {"native_value": None}
    if isinstance(raw, (list, tuple)):
        return {
            "native_value": len(raw),
            "extra_state_attributes": {"devices": list(raw)},
        }
    return {"native_value": None}


class ProductZF0HAdapter:
    """HUAWEI Home Panel S2 (ZF0H) — panel controls, diagnostics and broadcasts."""

    prod_id = "ZF0H"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        entities: list[EntitySpec] = []

        # --- switches (Profile RW bool + H5 dispatch evidence) ---------------
        for sid, field, key, name in (
            ("volSwitch", "on", "mute", "静音"),
            ("undisturbMode", "on", "do_not_disturb", "勿扰模式"),
        ):
            if context.has_service(sid) and _field(profile, sid, field) is not None:
                entities.append(_switch_spec(sid, field, key, name))

        # --- 勿扰时段（只读诊断） -------------------------------------------
        if (
            context.has_service("undisturbMode")
            and _field(profile, "undisturbMode", "start") is not None
        ):
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="do_not_disturb_range",
                    name="勿扰时段",
                    state=_undisturb_range,
                    metadata={"entity_category": "diagnostic"},
                )
            )

        # --- 面板模式（select：0=标准 / 10001=酒店） --------------------------
        if (
            context.has_service("panelMode")
            and _field(profile, "panelMode", "extendMode") is not None
        ):
            entities.append(
                EntitySpec(
                    platform="select",
                    key="panel_mode",
                    name="面板模式",
                    state=lambda ctx: {"current_option": _panel_mode_option(ctx)},
                    metadata={"options": list(_PANEL_MODE_LABELS.values())},
                    actions={"select_option": _select_panel_mode},
                )
            )

        # --- 电量 -----------------------------------------------------------
        if context.has_service("battery") and _field(profile, "battery", "level") is not None:
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="battery",
                    name="电量",
                    state=lambda ctx: {
                        "native_value": _number(ctx.value("battery", "level"))
                    },
                    metadata={
                        "unit": "%",
                        "device_class": "battery",
                        "state_class": "measurement",
                    },
                )
            )

        # --- 摆放状态 -------------------------------------------------------
        if (
            context.has_service("panelStatus")
            and _field(profile, "panelStatus", "status") is not None
        ):
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="panel_status",
                    name="摆放状态",
                    state=lambda ctx: {
                        "native_value": _enum_text(ctx, "panelStatus", "status")
                    },
                    metadata={},
                )
            )

        # --- Wi-Fi 信号 -----------------------------------------------------
        if context.has_service("netInfo") and _field(profile, "netInfo", "RSSI") is not None:
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="wifi_rssi",
                    name="Wi-Fi 信号",
                    state=lambda ctx: {
                        "native_value": _number(ctx.value("netInfo", "RSSI"))
                    },
                    metadata={
                        "unit": "dBm",
                        "device_class": "signal_strength",
                        "state_class": "measurement",
                    },
                )
            )

        # --- 固件版本（只读诊断） -------------------------------------------
        if context.has_service("update") and _field(profile, "update", "version") is not None:
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="firmware_version",
                    name="固件版本",
                    state=lambda ctx: {
                        "native_value": _text(ctx.value("update", "version"))
                    },
                    metadata={"entity_category": "diagnostic"},
                )
            )

        # --- 已扫描子设备（只读诊断） ---------------------------------------
        if context.has_service("devList") and _field(profile, "devList", "devList") is not None:
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="scanned_devices",
                    name="已扫描子设备",
                    state=_device_count,
                    metadata={"entity_category": "diagnostic"},
                )
            )

        # --- 文本播报（需框架 text 平台） -----------------------------------
        for sid, field, key, name in (
            ("communication", "directive", "voice_broadcast", "语音播报"),
            ("homeBroadcast", "text", "home_broadcast", "家庭广播"),
            ("speakerIfttt", "reportRoomTemp", "speak_room_temp", "播报室温内容"),
            ("speakerIfttt", "reportWeather", "speak_weather", "播报天气内容"),
        ):
            field_meta = _field(profile, sid, field)
            if not context.has_service(sid) or field_meta is None:
                continue
            maximum = int(field_meta.get("maxLength") or 255)
            entities.append(_text_spec(sid, field, key, name, maximum))

        return tuple(entities)


ADAPTER = ProductZF0HAdapter()

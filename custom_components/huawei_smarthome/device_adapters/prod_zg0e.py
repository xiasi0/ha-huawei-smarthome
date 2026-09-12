"""User-contributed protocol for Huawei product ZG0E.

Device: OSLO-SP6 智能面板 (deviceModel ``OSLO-SP6``, deviceTypeName
场景面板, protocolType ``PLC``) — a PLC scene panel with three relay
outputs, a touchscreen, a light sensor and temperature-hardware support.
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/ZG0E/ZG0E.json

Exposed entities (all payloads verified against the vendor H5 bundle,
single-file webpack build ``app.js``):

* ``switch`` "开关一/二/三"  <- ``switch1/2/3.on`` (relay outputs; the
  vendor ``Switches`` component dispatches ``{switchN: {on: Number(!on)}}``,
  cell labels 开关一/开关二/开关三 under the 继电器开关 page)
* ``switch`` "按键锁定"      <- ``childLockSwitch.on`` (按键锁定; vendor
  ``setChildButtonLock`` dispatches ``{childLockSwitch: {on: N}}``)
* ``switch`` "勿扰模式"      <- ``DNDmode.on`` (vendor home menu binds
  靠近亮屏 with ``active: !DNDmode.on`` and ``setDNDmode`` dispatches
  ``{DNDmode: {on: N}}``: on = 1 means proximity wake is suppressed)
* ``switch`` "屏幕亮度自动调节" <- ``display.on`` (显示设置 cell
  auto_adjustment 自动调节; ``setAutoScreenBri`` dispatches
  ``{display: {on: N}}``)
* ``switch`` "指示灯"        <- ``backlight.on`` (显示设置 cell
  ``backlight`` = 指示灯; ``setBacklightSwitch`` dispatches
  ``{backlight: {on: N}}``)
* ``switch`` "断电记忆"      <- ``memorySwitch.on`` (powerOutageMemory
  断电记忆; vendor dispatches ``{memorySwitch: {on: N}}``)
* ``switch`` "温度检测"      <- ``temperature.on`` (tempDetection 温度
  检测; ``switchModeClick`` dispatches ``{temperature: {on: N}}``)
* ``number`` "屏幕亮度"      <- ``display.brightness`` 0-100
  (screen_brightness 屏幕亮度; ``setScreenBri`` dispatches
  ``{display: {brightness: t}}``)
* ``number`` "指示灯亮度"    <- ``brightness.brightness`` 0-100 (the
  亮度 slider under the 指示灯 section; ``setBacklightBri`` dispatches
  ``{brightness: {brightness: t}}``)
* ``number`` "温度修正"      <- ``temperature.number``; the device stores
  tenths of a degree (-70..70) and the vendor tempCorrection cell renders
  ``number / 10 ℃`` while ``temperSetting`` dispatches
  ``{temperature: {number: 10 * v}}`` for v in -7.0..7.0 ℃ (step 0.1)
* ``sensor`` "室内光照"      <- ``luminance.current`` (indoor_luminance
  室内光照).  The Profile's own ``luminance.level`` enum describes the
  current value in lux bands (微光 0lx~50lx … 强光 >701lx), so the raw
  0-65535 value is treated as lux.  Read-only.
* ``sensor`` "故障状态"      <- ``faultDetection.code`` (0 正常 /
  1 过温保护 / 2 显示屏故障 / 4 温湿度传感器故障 / 8 接近传感器故障 /
  16 光传感器故障).  The vendor ``faultList`` computed decomposes the
  code as a bitmask (``code.toString(2)`` reversed, bit positions index
  the same labels), so composite codes are rendered as the joined labels
  of their set bits.  Read-only.

Deliberately *not* exposed:

* ``reboot`` — the vendor dispatches ``{reboot: {action: 2,
  devList: [{sn}]}}``: the panel acts as a gateway and reboots a batch of
  sub-devices plus the gateway, requiring the device ``sn`` which
  ``RemoteDeviceDescriptor`` does not carry.  Never degraded to
  ``action: 0`` — against the gateway semantics that would be a
  destructive batch operation.
* ``scene`` / ``button1``..``button20`` — the panel's scene buttons and
  their labels (``buttonN.name``) / bound scene counts (``buttonN.num``)
  are panel-local configuration managed from the panel itself; HA cannot
  trigger a panel button, so exposing 20 label sensors adds no value.
* ``display.pagemax/sequence/icon/hidden/modeList/fontsize`` — touchscreen
  page layout configuration (page order, icons, hidden flags, font size)
  maintained by the 面板管理/显示设置 H5 pages via composite string
  payloads; ``fontsize`` additionally has no dispatch anywhere in the H5.
* ``switchN.inversion`` — declared in the vendor schema but with no
  dispatch anywhere in the H5 bundle.
* ``obstructionDetected`` — zero references in the H5 bundle.
* ``faultDetection.phone`` — service hotline (950800), app managed.
* ``netInfo`` / ``netInfoCmd`` — read-only diagnostics and the App
  managed refresh trigger, consistent with the other adapters.
* 智能调优 (intelligent tuning) — the vendor dispatches
  ``{powerMode: {mode: ...}}`` but the Profile declares no ``powerMode``
  service, so the payload cannot be validated against the device model.
* 室内温度/室内湿度 — the ``indoor_temperature`` / ``indoor_humidity``
  language keys exist but are never rendered by any component, and the
  Profile declares no current-reading characteristic (``temperature``
  only carries the correction and the detection switch).

Unknown fault bits (not in the Profile enum) are rendered as 未知(N)
instead of being guessed.  This adapter was derived from the Profile and
vendor H5 bundle and is not yet verified on a physical device.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


def _service(profile: Any, sid: str) -> Any:
    if profile is None:
        return None
    for service in profile.get("services", ()):  # type: ignore[union-attr]
        if service.get("serviceId") == sid:
            return service
    return None


def _field(profile: Any, sid: str, name: str) -> dict[str, Any] | None:
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


def _int_state(context: DeviceContext, sid: str, name: str) -> int | None:
    raw = context.value(sid, name)
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _flag_state(sid: str, field_name: str):
    def state(context: DeviceContext) -> dict[str, Any]:
        raw = context.value(sid, field_name)
        if raw is None:
            return {}
        try:
            return {"is_on": bool(int(raw))}
        except (TypeError, ValueError):
            return {}

    return state


def _flag_action(sid: str, field_name: str, value: int):
    """Build a switch action setting ``sid.field`` to a fixed value.

    The vendor H5 toggles (``Number(!this[sid].on)``); HA uses explicit
    turn_on/turn_off actions, so each action sets the field directly.
    """

    async def action(context: DeviceContext, data: Mapping[str, Any]) -> None:
        await context.async_send_service(sid, {field_name: value})

    return action


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


# --- simple on/off switches ---------------------------------------------------

def _switch_entity(
    profile: Any,
    sid: str,
    key: str,
    name: str,
    note: str | None = None,
) -> EntitySpec | None:
    if _field(profile, sid, "on") is None:
        return None
    metadata = {"note": note} if note else {}
    return EntitySpec(
        platform="switch",
        key=key,
        name=name,
        state=_flag_state(sid, "on"),
        metadata=metadata,
        actions={
            "turn_on": _flag_action(sid, "on", 1),
            "turn_off": _flag_action(sid, "on", 0),
        },
    )


# --- numbers ------------------------------------------------------------------

def _percentage_number(
    profile: Any,
    sid: str,
    field_name: str,
    key: str,
    name: str,
) -> EntitySpec | None:
    field = _field(profile, sid, field_name)
    if field is None:
        return None
    maximum = _number(field.get("max"))
    minimum = _number(field.get("min"))
    if minimum is None or maximum is None or maximum <= minimum:
        return None

    def state(context: DeviceContext) -> dict[str, Any]:
        raw = _number(context.value(sid, field_name))
        if raw is None:
            return {}
        return {"native_value": _clamp(raw, minimum, maximum)}

    async def action(context: DeviceContext, data: Mapping[str, Any]) -> None:
        value = _clamp(float(data["value"]), minimum, maximum)
        await context.async_send_service(sid, {field_name: round(value)})

    return EntitySpec(
        platform="number",
        key=key,
        name=name,
        state=state,
        metadata={"min": minimum, "max": maximum, "step": 1},
        actions={"set_value": action},
    )


_TEMPERATURE_SID = "temperature"
_TEMPERATURE_FIELD = "number"
_TEMPERATURE_RAW_MIN = -70.0
_TEMPERATURE_RAW_MAX = 70.0


def _temperature_correction_number(profile: Any) -> EntitySpec | None:
    # The device stores tenths of a degree (-70..70).  The vendor renders
    # number / 10 ℃ and dispatches 10 * v for v in -7.0..7.0 ℃.
    if _field(profile, _TEMPERATURE_SID, _TEMPERATURE_FIELD) is None:
        return None

    def state(context: DeviceContext) -> dict[str, Any]:
        raw = _number(context.value(_TEMPERATURE_SID, _TEMPERATURE_FIELD))
        if raw is None:
            return {}
        raw = _clamp(raw, _TEMPERATURE_RAW_MIN, _TEMPERATURE_RAW_MAX)
        return {"native_value": round(raw / 10, 1)}

    async def action(context: DeviceContext, data: Mapping[str, Any]) -> None:
        value = _clamp(float(data["value"]), -7.0, 7.0)
        payload = int(round(value * 10))
        await context.async_send_service(
            _TEMPERATURE_SID, {_TEMPERATURE_FIELD: payload}
        )

    return EntitySpec(
        platform="number",
        key="temperature_correction",
        name="温度修正",
        state=state,
        metadata={"min": -7.0, "max": 7.0, "step": 0.1, "unit": "℃"},
        actions={"set_value": action},
    )


# --- sensors ------------------------------------------------------------------

def _luminance_sensor(profile: Any) -> EntitySpec | None:
    if _field(profile, "luminance", "current") is None:
        return None

    def state(context: DeviceContext) -> dict[str, Any]:
        raw = _int_state(context, "luminance", "current")
        if raw is None:
            return {}
        return {"native_value": raw}

    return EntitySpec(
        platform="sensor",
        key="indoor_luminance",
        name="室内光照",
        state=state,
        metadata={
            "unit": "lx",
            "device_class": "illuminance",
            "state_class": "measurement",
        },
    )


_FAULT_BITS: tuple[tuple[int, str], ...] = (
    (1, "过温保护"),
    (2, "显示屏故障"),
    (4, "温湿度传感器故障"),
    (8, "接近传感器故障"),
    (16, "光传感器故障"),
)


def _fault_sensor(profile: Any) -> EntitySpec | None:
    if _field(profile, "faultDetection", "code") is None:
        return None

    def state(context: DeviceContext) -> dict[str, Any]:
        code = _int_state(context, "faultDetection", "code")
        if code is None:
            return {}
        if code == 0:
            return {"native_value": "正常"}
        labels = []
        for bit, label in _FAULT_BITS:
            if code & bit:
                labels.append(label)
        unknown = code ^ sum(bit for bit, _ in _FAULT_BITS if code & bit)
        if unknown:
            labels.append(f"未知({unknown})")
        return {"native_value": "、".join(labels)}

    return EntitySpec(
        platform="sensor",
        key="fault_status",
        name="故障状态",
        state=state,
    )


# --- adapter ------------------------------------------------------------------


class ProductZG0EAdapter:
    prod_id = "ZG0E"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        specs: list[EntitySpec] = []

        # Relay outputs.  The vendor Switches component dispatches
        # {switchN: {on: Number(!on)}}; the 继电器开关 page labels the
        # three cells 开关一/开关二/开关三.
        for index in (1, 2, 3):
            spec = _switch_entity(profile, f"switch{index}", f"relay_{index}", f"开关{['一','二','三'][index - 1]}")
            if spec is not None:
                specs.append(spec)

        for spec in (
            _switch_entity(profile, "childLockSwitch", "child_lock", "按键锁定"),
            _switch_entity(profile, "DNDmode", "dnd_mode", "勿扰模式"),
            _switch_entity(profile, "display", "screen_auto_adjust", "屏幕亮度自动调节"),
            _switch_entity(profile, "backlight", "indicator_light", "指示灯"),
            _switch_entity(profile, "memorySwitch", "power_outage_memory", "断电记忆"),
            _switch_entity(profile, "temperature", "temperature_detection", "温度检测"),
        ):
            if spec is not None:
                specs.append(spec)

        for spec in (
            _percentage_number(profile, "display", "brightness", "screen_brightness", "屏幕亮度"),
            _percentage_number(profile, "brightness", "brightness", "indicator_brightness", "指示灯亮度"),
            _temperature_correction_number(profile),
        ):
            if spec is not None:
                specs.append(spec)

        for spec in (_luminance_sensor(profile), _fault_sensor(profile)):
            if spec is not None:
                specs.append(spec)

        return tuple(specs)


ADAPTER = ProductZG0EAdapter()

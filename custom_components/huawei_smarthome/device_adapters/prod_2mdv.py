"""User-contributed protocol for Huawei product 2MDV (杜亚 PLC 版开合帘电机 尊享款 H2).

Profile: opener.{current R, target RW} 0..100% / action.action enum
(0关/1开/2暂停/3开停/4关停/5开关停) / speed.motorSpeed 1..100% /
switchSpeed.action enum 0一档/1二档/2三档 / changeDirection.action enum /
placeMemory.{action W, code R} / lightSwitch.action enum 0关1开 /
selfCheck.on bool / faultDetection.{status, code} / netInfo.

H5 evidence (h5_001 webpack bundle, DOOYA curtain motor):
- open/close/stop buttons: setDevInfo({action:{action:1|0|2}}) (clickOpen /
  clickClose / clickStop, both home and big-curtain pages).
- position slider touchend: setDevInfo({opener:{target: 100-this.current}})
  — the 100-x is the H5's mirrored canvas transform; the device value is
  plain 0..100 where quickmenu defines opener/target=100 全开, 0 全关.
- speed semimodal submit: setDevInfo({speed:{motorSpeed: N}}).
- speed gears radio: setDevInfo({switchSpeed:{action: 0|1|2}}).
- indicator light: setDevInfo({lightSwitch:{action: 0|1}}) toggled from the
  current lwmpSwitch state.
- self check: clickSelf -> setDevInfo({selfCheck:{on: 1}}); the H5 then
  watches selfCheck.on fall back to 0 and toasts "检测完成" (a pulse, so a
  button rather than a switch).
- direction page confirm: setDevInfo({changeDirection:{action: 1}});
  the built-in validation schema declares changeDirection.action as
  mean:"启用" range:[1] — only value 1 is ever written. i18n: "是否更换设备
  转向？...更换设备转向后，行程需要重新设置".
- built-in validation schema (part of this bundle) declares every service
  above with the same labels as the Profile, e.g. opener.target
  mean:["关了"] range 0..100, action.action mean ["关","开","暂停",...].
- commitHilink validates every reported field against that schema before
  storing, so state values are the raw characteristic values.

Not exposed (宁可不出):
- placeMemory.action IS wired into buttons below — but note the H5 never
  dispatches it (the app only *displays* placeMemory.code and warns that
  travel limits must be re-set after a direction change); the write
  semantics come from the bundle's validation schema (mean ["设置限位",
  "清除全部限位"], range [0,1]) plus the Profile. 清除全部限位 wipes the
  motor's travel limits — it is exposed as an explicit button because it
  is a documented device function, but it should be pressed deliberately.
- action.action values 3/4/5 (开停/关停/开关停): only 0/1/2 have send
  evidence; the others are treated as reported states, never sent.
- update: the schema declares it, but no UI dispatch site exists in the
  bundle -> no button.
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


def _enum_key(value: Any) -> str | None:
    number = _number(value)
    return str(int(number)) if number is not None else _text(value)


def _enum_text(field: Mapping[str, Any], value: Any) -> str | None:
    """Map a raw characteristic value to its Profile enum label.

    Unknown values return None (unknown) instead of guessing a label.
    """
    if value is None or isinstance(value, bool):
        return None
    return _enum_labels(field).get(_enum_key(value) or "")


def _enum_payload(value: str, field: Mapping[str, Any]) -> Any:
    """Convert a selected label back to the wire value (ints for numeric enums)."""
    for key, label in _enum_labels(field).items():
        if label == value:
            try:
                return int(float(key))
            except (TypeError, ValueError):
                return key
    return None


async def _send_action_value(context: DeviceContext, value: int) -> None:
    await context.async_send_service("action", {"action": value})


async def _cover_open(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await _send_action_value(context, 1)


async def _cover_close(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await _send_action_value(context, 0)


async def _cover_stop(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await _send_action_value(context, 2)


class Product2MDVAdapter:
    prod_id = "2MDV"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()
        entities: list[EntitySpec] = []
        entities.extend(self._cover_entity(context, profile))
        entities.extend(self._speed_entities(context, profile))
        entities.extend(self._light_entity(context, profile))
        entities.extend(self._button_entities(context, profile))
        entities.extend(self._fault_entities(context, profile))
        entities.extend(self._net_info_entities(context, profile))
        return tuple(entities)

    def _cover_entity(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        if not context.has_service("opener") or not context.has_service("action"):
            return ()
        target_field = _field(profile, "opener", "target")
        if target_field is None:
            return ()

        def cover_state(device: DeviceContext) -> Mapping[str, Any]:
            position = _number(device.value("opener", "current"))
            return {
                "current_position": position,
                # quickmenu: opener/target=0 -> 全关
                "is_closed": None if position is None else position == 0,
            }

        async def set_position(context: DeviceContext, data: Mapping[str, Any]) -> None:
            clamped = _clamp_to_profile(data.get("position"), target_field)
            if clamped is None:
                raise ValueError(f"2MDV invalid curtain position: {data.get('position')!r}")
            await context.async_send_service("opener", {"target": clamped})

        return (
            EntitySpec(
                platform="cover",
                key="curtain",
                name=None,
                state=cover_state,
                metadata={},
                actions={
                    "open": _cover_open,
                    "close": _cover_close,
                    "stop": _cover_stop,
                    "set_position": set_position,
                },
            ),
        )

    def _speed_entities(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        entities: list[EntitySpec] = []

        if context.has_service("switchSpeed") and _field(
            profile, "switchSpeed", "action"
        ) is not None:
            gear_field = _field(profile, "switchSpeed", "action")
            labels = _enum_labels(gear_field)
            options: list[str] = []
            for raw in (
                option.get("enumVal") for option in gear_field.get("enumList", ()) or ()
            ):
                if raw is None:
                    continue
                label = labels.get(str(raw))
                if label is None:
                    continue
                if label in options:
                    label = f"{label} (rawValue)"
                options.append(label)

            def gear_state(device: DeviceContext) -> Mapping[str, Any]:
                value = device.value("switchSpeed", "action")
                if value is None or isinstance(value, bool):
                    return {"current_option": None}
                return {"current_option": labels.get(_enum_key(value) or "")}

            async def select_gear(context: DeviceContext, data: Mapping[str, Any]) -> None:
                value = _enum_payload(data.get("option") or "", gear_field)
                if value is None:
                    raise ValueError(f"2MDV unknown speed gear: {data.get('option')!r}")
                await context.async_send_service("switchSpeed", {"action": value})

            entities.append(
                EntitySpec(
                    platform="select",
                    key="speed_gear",
                    name="开合速度",
                    state=gear_state,
                    metadata={"options": tuple(options)},
                    actions={"select_option": select_gear},
                )
            )

        if context.has_service("speed") and _field(
            profile, "speed", "motorSpeed"
        ) is not None:
            speed_field = _field(profile, "speed", "motorSpeed")
            value_range = _profile_range(speed_field)
            if value_range is not None:
                minimum, maximum = value_range
                step = _number(speed_field.get("step")) or 1.0

                def speed_state(device: DeviceContext) -> Mapping[str, Any]:
                    return {
                        "native_value": _number(device.value("speed", "motorSpeed"))
                    }

                async def set_speed(context: DeviceContext, data: Mapping[str, Any]) -> None:
                    clamped = _clamp_to_profile(data.get("value"), speed_field)
                    if clamped is None:
                        raise ValueError(f"2MDV invalid motor speed: {data.get('value')!r}")
                    await context.async_send_service("speed", {"motorSpeed": clamped})

                entities.append(
                    EntitySpec(
                        platform="number",
                        key="motor_speed",
                        name="无极调速",
                        state=speed_state,
                        metadata={
                            "min": minimum,
                            "max": maximum,
                            "step": step,
                            "unit": "%",
                        },
                        actions={"set_value": set_speed},
                    )
                )
        return tuple(entities)

    def _light_entity(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        if not context.has_service("lightSwitch"):
            return ()
        if _field(profile, "lightSwitch", "action") is None:
            return ()

        def light_state(device: DeviceContext) -> Mapping[str, Any]:
            return {"is_on": _number(device.value("lightSwitch", "action")) == 1}

        async def turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
            await context.async_send_service("lightSwitch", {"action": 1})

        async def turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
            await context.async_send_service("lightSwitch", {"action": 0})

        return (
            EntitySpec(
                platform="switch",
                key="indicator",
                name="指示灯",
                state=light_state,
                metadata={},
                actions={"turn_on": turn_on, "turn_off": turn_off},
            ),
        )

    def _button_entities(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        entities: list[EntitySpec] = []

        def button(
            sid: str,
            field_name: str,
            value: Any,
            key: str,
            name: str,
            guard_sid: str | None = None,
        ) -> EntitySpec | None:
            target_sid = guard_sid or sid
            if not context.has_service(target_sid):
                return None
            if _field(profile, sid, field_name) is None:
                return None

            async def press(context: DeviceContext, _data: Mapping[str, Any]) -> None:
                await context.async_send_service(sid, {field_name: value})

            return EntitySpec(
                platform="button",
                key=key,
                name=name,
                state=lambda device: {},
                metadata={},
                actions={"press": press},
            )

        # placeMemory.action: write semantics from the bundle's validation
        # schema (mean ["设置限位","清除全部限位"], range [0,1]); the H5 only
        # displays placeMemory.code. 清除 wipes travel limits — deliberate use.
        for sid, field_name, value, key, name, guard in (
            ("placeMemory", "action", 0, "set_limit", "设置限位", "placeMemory"),
            ("placeMemory", "action", 1, "clear_limits", "清除全部限位", "placeMemory"),
            ("changeDirection", "action", 1, "reverse_direction", "更换设备转向", "changeDirection"),
            ("selfCheck", "on", 1, "self_check", "功能检测", "selfCheck"),
        ):
            spec = button(sid, field_name, value, key, name, guard)
            if spec is not None:
                entities.append(spec)
        return tuple(entities)

    def _fault_entities(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        entities: list[EntitySpec] = []
        if context.has_service("faultDetection"):
            code_field = _field(profile, "faultDetection", "code")
            if code_field is not None:

                def fault_state(device: DeviceContext) -> Mapping[str, Any]:
                    return {
                        "native_value": _enum_text(
                            code_field,
                            device.value("faultDetection", "code"),
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

            status_field = _field(profile, "faultDetection", "status")
            if status_field is not None:

                def problem_state(device: DeviceContext) -> Mapping[str, Any]:
                    # Profile enum: 1=设备运行异常, 0=运行正常，无错误
                    status = _number(device.value("faultDetection", "status"))
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

        if context.has_service("placeMemory"):
            limit_field = _field(profile, "placeMemory", "code")
            if limit_field is not None:

                def limit_state(device: DeviceContext) -> Mapping[str, Any]:
                    return {
                        "native_value": _enum_text(
                            limit_field,
                            device.value("placeMemory", "code"),
                        )
                    }

                entities.append(
                    EntitySpec(
                        platform="sensor",
                        key="limit_status",
                        name="限位状态",
                        state=limit_state,
                        metadata={},
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


ADAPTER = Product2MDVAdapter()

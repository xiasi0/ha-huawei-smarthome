"""Product adapter for the AD310 camera (2POO, 海雀智能摄像头 双雀Max 64GB).

This product is uiType PLUGIN — the 海雀 app drives it through a native
plugin, so there is NO H5 bundle and no setDeviceInfo dispatch evidence.
Everything below is therefore documented directly by the Profile contract
(service/characteristic enums declare the write semantics), kept to the
simple subset that such a contract can carry:

* ``switch.on`` 摄像头 / ``videoSwitch.on`` 摄像开关 / ``shootSwitch.on``
  拍照开关 / ``cruiseSwitch.on`` 全景巡航 / ``cruiseSwitch2.on`` 全景
  巡航-摄像头2 — plain bool switches; HA sends the explicit target value.
* ``alarmEvent.alarm`` / ``alarmEvent2.alarm`` (1=有告警, 0=无告警) —
  read-only alarm state per camera → binary_sensor.
* ``visitPoint1..12.move`` (1=移到该预置点, 0=无动作) — preset-point goto
  triggers → buttons.  visitPoint1..6 belong to camera 1, 7..12 to
  camera 2 (Profile serviceName suffixes -摄像头2).  The dual-camera
  layout mirrors the H5-free Profile structure.

Not exposed (宁可不出): the per-alarm-type flags on alarmEvent(N)
(babyCry/humanBody/audio/video/animal are event switches managed in the
plugin, not simple state), voip (call flow needs the app), visitPoint
enable/name (configuration belongs to the camera UI), deviceInfo,
logReport, update.
"""

from __future__ import annotations

from typing import Any, Mapping

from .api import EntitySpec
from .context import DeviceContext


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


def _flag_value(raw: Any) -> bool | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    try:
        number = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if number == 1:
        return True
    if number == 0:
        return False
    return None


class Product2POOAdapter:
    """AD310 dual camera (2POO) — Profile-contract entities only (PLUGIN)."""

    prod_id = "2POO"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        entities: list[EntitySpec] = []

        # --- switches -------------------------------------------------------
        for sid, key, name in (
            ("switch", "camera_switch", "摄像头"),
            ("videoSwitch", "video_switch", "摄像开关"),
            ("shootSwitch", "shoot_switch", "拍照开关"),
            ("cruiseSwitch", "cruise_switch", "全景巡航"),
            ("cruiseSwitch2", "cruise_switch_2", "全景巡航-摄像头2"),
        ):
            if not context.has_service(sid) or _field(profile, sid, "on") is None:
                continue

            async def turn_on(ctx: DeviceContext, data: Mapping[str, Any], _sid=sid) -> None:
                del data
                await ctx.async_send_service(_sid, {"on": 1})

            async def turn_off(ctx: DeviceContext, data: Mapping[str, Any], _sid=sid) -> None:
                del data
                await ctx.async_send_service(_sid, {"on": 0})

            entities.append(
                EntitySpec(
                    platform="switch",
                    key=key,
                    name=name,
                    state=lambda ctx, _sid=sid: {
                        "is_on": _flag_value(ctx.value(_sid, "on"))
                    },
                    metadata={},
                    actions={"turn_on": turn_on, "turn_off": turn_off},
                )
            )

        # --- alarm states -----------------------------------------------------
        for sid, key, name in (
            ("alarmEvent", "camera1_alarm", "摄像头1告警"),
            ("alarmEvent2", "camera2_alarm", "摄像头2告警"),
        ):
            if not context.has_service(sid) or _field(profile, sid, "alarm") is None:
                continue
            entities.append(
                EntitySpec(
                    platform="binary_sensor",
                    key=key,
                    name=name,
                    state=lambda ctx, _sid=sid: {
                        "is_on": _flag_value(ctx.value(_sid, "alarm"))
                    },
                    metadata={},
                )
            )

        # --- preset-point goto buttons -----------------------------------------
        for index in range(1, 13):
            sid = f"visitPoint{index}"
            if not context.has_service(sid) or _field(profile, sid, "move") is None:
                continue
            camera = "摄像头2" if index >= 7 else "摄像头1"

            async def move(ctx: DeviceContext, data: Mapping[str, Any], _sid=sid) -> None:
                del data
                # Profile enum: move 1=移到该预置点 (0=无动作, never sent).
                await ctx.async_send_service(_sid, {"move": 1})

            entities.append(
                EntitySpec(
                    platform="button",
                    key=f"goto_preset_{index}",
                    name=f"移到预置点{index}({camera})",
                    state=lambda ctx: {},
                    metadata={},
                    actions={"press": move},
                )
            )

        return tuple(entities)


ADAPTER = Product2POOAdapter()

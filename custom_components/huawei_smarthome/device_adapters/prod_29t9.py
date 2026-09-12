"""Product adapter for the BL5021R smart water valve (29T9, 智能电动水阀, PLC).

Profile: switch.on bool / rotation.{action enum(0=自动清洗, 1=未触发),
status enum(0=清洗中, 1=清洗完成, 2=阀门正在运行请稍后重试, 3=阀门无动作)}
/ faultDetection.{status 0正常/1异常, code 0正常/1 flash读写异常/2 阀门异常,
reset 0=上电/1=手动重启}.

H5 evidence (h5_001 single-chunk bundle, title 智能电动水阀):

- valve toggle: ``hilink.setDeviceInfo("0", {switch:{on: 0|1}})`` with the
  explicit target value (the card flips from the cached state; HA sends
  the target directly).
- auto clean: ``{rotation:{action:0}}`` from the 自动清洗 card
  (setClearInfo).  The H5 guards the send — refused while a self-check is
  running, when faultDetection.status is 1 (then it jumps the UI straight
  to status 3) and while a clean is already in flight; the HA button
  simply sends and the device rejects/refuses via the status reports.
- rotation.status report: 1=清洗完成 raises a toast then the UI falls
  back to 阀门无动作 after 3 s; 2=阀门正在运行，请稍后重试 shows the busy
  tip.  Values are raw characteristic values, labels come from the
  Profile enum (matches the H5 i18n: rotation=清洗中, finishClear=清洗
  已完成, error_ele_tip=阀门正在运行，请稍后重试).
- faultDetection.code: i18n error_normal=无异常 / error_flash=Flash 读写
  异常 / error_ele=阀门异常 — same labels as the Profile enum.
- faultDetection.status: the banner shows when status==1 → 故障告警
  binary_sensor (problem device class).

Not exposed (宁可不出):

* ``faultDetection.action`` — the H5 sends it ({action:0} 功能自检,
  {action:1} 重启, {action:2} 恢复出厂设置) but the 29T9 Profile does
  NOT declare an ``action`` characteristic on faultDetection; sending an
  undeclared characteristic is outside the device contract.  重启 and
  恢复出厂设置 are also destructive, so they stay out even if a future
  Profile revision declares the field.
* ``faultDetection.reset`` (0=上电/1=手动重启) — the H5 only ever READS
  it: the device reports reset=1 to confirm a manual restart succeeded
  ("重启成功" toast) and the store resets it to 0 otherwise.  It is a
  transient handshake flag, not a stable state — no HA mapping.
"""

from __future__ import annotations

from typing import Any, Mapping

from .api import EntitySpec
from .context import DeviceContext

_SWITCH_SID = "switch"
_SWITCH_FIELD = "on"

_ROTATION_SID = "rotation"
_ROTATION_ACTION_FIELD = "action"

_FAULT_SID = "faultDetection"
_FAULT_STATUS_FIELD = "status"
_FAULT_CODE_FIELD = "code"


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


def _enum_labels(field: Mapping[str, Any]) -> dict[int, str]:
    labels: dict[int, str] = {}
    for option in field.get("enumList", ()) or ():
        if not isinstance(option, Mapping):
            continue
        try:
            key = int(str(option.get("enumVal")).strip())
        except (TypeError, ValueError):
            continue
        labels[key] = str(option.get("descCh") or option.get("enumVal"))
    return labels


def _enum_text(context: DeviceContext, sid: str, name: str) -> str | None:
    """Map a reported enum value onto its Profile label; unknown -> None."""
    raw = context.value(sid, name)
    if raw is None or isinstance(raw, bool):
        return None
    try:
        number = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    field = _field(context.profile, sid, name)
    if field is None:
        return None
    return _enum_labels(field).get(number)


def _flag_value(raw: Any) -> bool | None:
    """Reported switch value → bool; anything outside 0/1 stays unknown."""

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


class Product29T9Adapter:
    """BL5021R smart water valve (29T9)."""

    prod_id = "29T9"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        entities: list[EntitySpec] = []

        # --- valve switch ----------------------------------------------------
        if context.has_service(_SWITCH_SID) and _field(
            profile, _SWITCH_SID, _SWITCH_FIELD
        ) is not None:
            async def turn(ctx: DeviceContext, data: Mapping[str, Any]) -> None:
                del data
                await ctx.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 1})

            async def turn_off(ctx: DeviceContext, data: Mapping[str, Any]) -> None:
                del data
                await ctx.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 0})

            entities.append(
                EntitySpec(
                    platform="switch",
                    key="valve",
                    name=None,
                    state=lambda ctx: {
                        "is_on": _flag_value(ctx.value(_SWITCH_SID, _SWITCH_FIELD))
                    },
                    metadata={},
                    actions={"turn_on": turn, "turn_off": turn_off},
                )
            )

        # --- auto clean button ------------------------------------------------
        if context.has_service(_ROTATION_SID) and _field(
            profile, _ROTATION_SID, _ROTATION_ACTION_FIELD
        ) is not None:
            async def clean(ctx: DeviceContext, data: Mapping[str, Any]) -> None:
                del data
                # H5 setClearInfo: {rotation:{action:0}} — the only value
                # ever sent (1=未触发 is a reported state, never written).
                await ctx.async_send_service(_ROTATION_SID, {_ROTATION_ACTION_FIELD: 0})

            entities.append(
                EntitySpec(
                    platform="button",
                    key="auto_clean",
                    name="自动清洗",
                    state=lambda ctx: {},
                    metadata={},
                    actions={"press": clean},
                )
            )

        # --- clean status -----------------------------------------------------
        if context.has_service(_ROTATION_SID) and _field(
            profile, _ROTATION_SID, "status"
        ) is not None:
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="clean_status",
                    name="清洗状态",
                    state=lambda ctx: {
                        "native_value": _enum_text(ctx, _ROTATION_SID, "status")
                    },
                    metadata={},
                )
            )

        # --- fault state --------------------------------------------------------
        if context.has_service(_FAULT_SID) and _field(
            profile, _FAULT_SID, _FAULT_CODE_FIELD
        ) is not None:
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="fault_state",
                    name="故障状态",
                    state=lambda ctx: {
                        "native_value": _enum_text(
                            ctx, _FAULT_SID, _FAULT_CODE_FIELD
                        )
                    },
                    metadata={},
                )
            )

        # --- fault alarm ----------------------------------------------------------
        if context.has_service(_FAULT_SID) and _field(
            profile, _FAULT_SID, _FAULT_STATUS_FIELD
        ) is not None:
            entities.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="fault_problem",
                    name="故障告警",
                    # Profile enum: 1=异常, 0=正常
                    state=lambda ctx: {
                        "is_on": (
                            None
                            if _flag_value(
                                ctx.value(_FAULT_SID, _FAULT_STATUS_FIELD)
                            ) is None
                            else bool(
                                _flag_value(ctx.value(_FAULT_SID, _FAULT_STATUS_FIELD))
                            )
                        )
                    },
                    metadata={"device_class": "problem"},
                )
            )

        return tuple(entities)


ADAPTER = Product29T9Adapter()

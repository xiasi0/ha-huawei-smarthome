"""User-contributed protocol for Huawei product 2982.

Device: 名豆之约 智能插座10A / smart plug 10A (deviceModel ``ZCZ001``,
manufacturer ``广州万烨``, protocolType ``WiFi``).
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/2982/2982.json

Exposed entities:

* ``switch`` (device name)   <- ``switch.on`` (1 开 / 0 关; vendor
                               ``handleChangeSwitch`` dispatches
                               ``{switch: {on: N}}``)
* ``select`` "保护功能"      <- ``protect.protect`` (0 无保护功能 /
                               1 充电保护 / 2 家电保护; vendor
                               ``handleProtect`` dispatches
                               ``{protect: {protect: N}}``)
* ``sensor`` "实时功率"      <- ``powerElectricity.power`` in watts (the
                               vendor passes the raw report straight to the
                               UI and appends the 瓦 unit)
* ``sensor`` "总用电量"      <- ``powerElectricity.TotalElectricity``
                               divided by 1000: the vendor store renders
                               ``TotalElectricity / 1e3`` next to the
                               千瓦时 (kWh) unit
* ``sensor`` "用电量"        <- ``electricity.electricity`` divided by
                               1000: the statistics page requests cloud
                               aggregates for this same sid/character and
                               renders ``sum / 1e3`` as kWh, so the device
                               raw value is watt-hours like the total
* ``sensor`` "保护倒计时"    <- ``protectTimer.Timer`` in seconds (the
                               vendor formats it as MM:SS via
                               ``floor(t / 60)`` / ``t % 60``; it counts
                               down to the protection auto-off described
                               by protectTip: 设备功率累计10分钟不高于
                               10瓦，自动关闭插座)

Deliberately *not* exposed:

* ``timer`` / ``delay`` — array-of-objects schedules whose item schema the
  Profile does not document (the vendor manages them through a dedicated
  timing page with create/update/delete actions and local countdown
  bookkeeping).  No entity over an undocumented payload shape.
* ``update`` / ``netInfo`` — OTA and read-only diagnostics, consistent with
  the other adapters.

Unknown ``protect`` values map to unknown, never guessed.  This adapter was
derived from the Profile and vendor H5 bundle and is not yet verified on a
physical device.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_SWITCH_SID = "switch"
_SWITCH_FIELD = "on"

_PROTECT_SID = "protect"
_PROTECT_FIELD = "protect"

_POWER_SID = "powerElectricity"
_POWER_FIELD = "power"
_TOTAL_FIELD = "TotalElectricity"

_ELECTRICITY_SID = "electricity"
_ELECTRICITY_FIELD = "electricity"

_TIMER_SID = "protectTimer"
_TIMER_FIELD = "Timer"

# powerElectricity.TotalElectricity is watt-hours; the vendor store renders
# TotalElectricity / 1e3 with the 千瓦时 unit.
_WH_PER_KWH = 1000

_PROTECT_OPTIONS: tuple[tuple[int, str], ...] = (
    (0, "无保护功能"),
    (1, "充电保护"),
    (2, "家电保护"),
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


async def _turn_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 1})


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service(_SWITCH_SID, {_SWITCH_FIELD: 0})


class Product2982Adapter:
    """Keep all 2982 entity and command choices in this file."""

    prod_id = "2982"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        specs: list[EntitySpec] = []

        # --- main switch ------------------------------------------------------
        if context.has_service(_SWITCH_SID) and _field(
            profile, _SWITCH_SID, _SWITCH_FIELD
        ) is not None:
            def switch_state(device: DeviceContext) -> Mapping[str, Any]:
                return {"is_on": _bool(device.value(_SWITCH_SID, _SWITCH_FIELD))}

            specs.append(
                EntitySpec(
                    platform="switch",
                    key="switch",
                    name=None,  # falls back to the device name
                    state=switch_state,
                    actions={
                        "turn_on": _turn_on,
                        "turn_off": _turn_off,
                    },
                )
            )

        # --- protection mode select -------------------------------------------
        if context.has_service(_PROTECT_SID) and _field(
            profile, _PROTECT_SID, _PROTECT_FIELD
        ) is not None:
            def protect_state(device: DeviceContext) -> Mapping[str, Any]:
                number = _number(
                    device.value(_PROTECT_SID, _PROTECT_FIELD)
                )
                for enum_value, label in _PROTECT_OPTIONS:
                    if number == enum_value:
                        return {"current_option": label}
                return {"current_option": None}

            async def protect_select_option(
                context: DeviceContext,
                data: Mapping[str, Any],
            ) -> None:
                option = data.get("option")
                for enum_value, label in _PROTECT_OPTIONS:
                    if option == label:
                        # Vendor handleProtect dispatches {protect:{protect:N}}.
                        await context.async_send_service(
                            _PROTECT_SID,
                            {_PROTECT_FIELD: enum_value},
                        )
                        return
                raise ValueError(f"unknown option: {option!r}")

            specs.append(
                EntitySpec(
                    platform="select",
                    key="protect",
                    name="保护功能",
                    state=protect_state,
                    metadata={"options": [label for _, label in _PROTECT_OPTIONS]},
                    actions={"select_option": protect_select_option},
                )
            )

        # --- power (read-only, watts) ------------------------------------------
        if context.has_service(_POWER_SID) and _field(
            profile, _POWER_SID, _POWER_FIELD
        ) is not None:
            def power_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "native_value": _number(
                        device.value(_POWER_SID, _POWER_FIELD)
                    )
                }

            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="power",
                    name="实时功率",
                    state=power_state,
                    metadata={
                        # Vendor UI appends powerUnit 瓦 to the raw value.
                        "unit": "W",
                        "state_class": "measurement",
                    },
                )
            )

        # --- total energy (read-only, Wh -> kWh) -------------------------------
        if context.has_service(_POWER_SID) and _field(
            profile, _POWER_SID, _TOTAL_FIELD
        ) is not None:
            def total_energy_state(device: DeviceContext) -> Mapping[str, Any]:
                value = _number(device.value(_POWER_SID, _TOTAL_FIELD))
                if value is None:
                    return {"native_value": None}
                return {"native_value": value / _WH_PER_KWH}

            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="total_energy",
                    name="总用电量",
                    state=total_energy_state,
                    metadata={
                        # Vendor store: TotalElectricity / 1e3 with 千瓦时.
                        "unit": "kWh",
                        "state_class": "total_increasing",
                    },
                )
            )

        # --- stage energy (read-only, Wh -> kWh) -------------------------------
        if context.has_service(_ELECTRICITY_SID) and _field(
            profile, _ELECTRICITY_SID, _ELECTRICITY_FIELD
        ) is not None:
            def energy_state(device: DeviceContext) -> Mapping[str, Any]:
                value = _number(
                    device.value(_ELECTRICITY_SID, _ELECTRICITY_FIELD)
                )
                if value is None:
                    return {"native_value": None}
                return {"native_value": value / _WH_PER_KWH}

            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="energy",
                    name="用电量",
                    state=energy_state,
                    metadata={
                        # The statistics page fetches cloud aggregates for this
                        # sid/character and renders sum / 1e3 as 千瓦时, so the
                        # device raw value is watt-hours like the total.
                        "unit": "kWh",
                        "state_class": "total_increasing",
                    },
                )
            )

        # --- protection countdown (read-only, seconds) --------------------------
        if context.has_service(_TIMER_SID) and _field(
            profile, _TIMER_SID, _TIMER_FIELD
        ) is not None:
            def countdown_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "native_value": _number(
                        device.value(_TIMER_SID, _TIMER_FIELD)
                    )
                }

            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="protect_countdown",
                    name="保护倒计时",
                    state=countdown_state,
                    metadata={
                        # Vendor formatProtectTime: floor(t/60) : t%60 -> MM:SS.
                        "unit": "s",
                        "state_class": "measurement",
                    },
                )
            )

        return tuple(specs)


ADAPTER = Product2982Adapter()

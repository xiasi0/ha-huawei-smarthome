"""User-contributed protocol for Huawei product K10H.

Device: 华为路由 AX3 Pro (HUAWEI WiFi AX3 Pro, deviceModel ``WS7200-10``).
prodId: ``K10H``.

Data sources
============

* A sanitized real-device state snapshot captured on 2026-10-18
  (``state_K10H.json``).  It contains the service list and representative
  values but no credentials, SSID/BSSID or MAC addresses.
* The public Profile ``profiles/K10H.cdn.json`` only carries metadata
  (``prodId`` / ``deviceName`` / ``offeringCode``) and declares **no**
  ``services`` or ``characteristics``.  This adapter therefore never reads
  field definitions from the Profile; it only uses ``context.has_service``
  and ``context.value`` against the runtime service cache.
* Weekly-report timing: Huawei's official support page for the Smart Life
  app's router weekly report says the report is generated every Friday at
  21:00 China Standard Time.  The snapshot value ``weekly.time =
  20261016T130051Z`` is exactly Friday 13:00:51 UTC / 21:00:51 CST, which
  matches that description.
* Cross-product OTA evidence only (not K10H proof): ``prod_2CYN`` declares
  ``update.action`` as 0 = check for updates / 1 = start update, and
  ``prod_2MZN`` declares ``update.autoUpdateOn`` as a read-write int meaning
  "automatic update switch".  K10H's Profile declares neither field.

Exposed read-only entities (11)
===============================

* ``binary_sensor`` online status            <- ``context.available``
* ``sensor``        Wi-Fi SSID               <- ``stsSession.SSID``
* ``sensor``        Wi-Fi BSSID              <- ``stsSession.BSSID``
* ``sensor``        devices seen this week   <- ``weekly.deviceNum``
* ``binary_sensor`` weekly report enabled     <- ``weekly.enable``
* ``sensor``        weekly report time        <- ``weekly.time``
* ``sensor``        firmware version          <- ``update.version``
* ``binary_sensor`` automatic update enabled  <- ``update.autoUpdateOn``
* ``event``         device access             <- ``deviceAccess`` pushes
* ``event``         child device push         <- ``childPush`` pushes
* ``event``         green channel join        <- ``GreenChnJoin`` pushes

Event entities fire only on accepted live MQTT service updates; the initial
snapshot is never replayed, so historical records do not fire at startup.

Deliberately not exposed
========================

* ``router.event`` — its value carries ``UserInfo[].UserId`` / ``Token`` and
  is the plugin authentication/event channel.  This file never reads it, so
  no entity, log line or diagnostic output can leak those values.
* ``ctlCapability.authcode`` — credential, ignored.
* ``NPS`` — satisfaction survey / purchase guidance, not device state.
* ``stsSession.on`` — 0 while the router is online and broadcasting SSID, so
  it is not a power or availability flag.
* ``wifimodeswitching.indication`` — enum meaning (0/1/2) unconfirmed.
* ``weekly.flow`` / ``weekly.maxSpeed`` — semantics are flow and top speed,
  but units are unknown and both were 0 on the real device.  They are only
  exposed as raw attributes of the weekly device-count sensor; no sensor
  with a fabricated MB/GB or Mbps unit is created.
* ``batchCmd`` / ``homeCenter`` / ``cord`` / ``rule`` / ``channelAlarm`` /
  ``attacker`` / ``multiwan`` / ``apppush`` / ``pluginStatus`` /
  ``shareAbility`` / ``netInfo`` — empty objects with no verifiable field
  semantics in the snapshot.

Verification status
===================

Verified (offline, from the sanitized snapshot): the services and fields
read below exist, their values parse with the conversions in this file, and
the adapter produces 11 entity specs without raising.

Not verified: no live Home Assistant run and no real-device MQTT command
capture.  ``update.version`` semantics (current vs available firmware),
``weekly.deviceNum`` counting window, weekly flow/speed units, event push
behavior, and every write payload remain unconfirmed.

"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_PROD_ID = "K10H"


_SID_STS = "stsSession"
_SID_WEEKLY = "weekly"
_SID_UPDATE = "update"
_SID_DEVICE_ACCESS = "deviceAccess"
_SID_CHILD_PUSH = "childPush"
_SID_GREEN_CHANNEL = "GreenChnJoin"


# ---------------------------------------------------------------------------
# Value conversion helpers
# ---------------------------------------------------------------------------


def _as_text(value: Any) -> str | None:
    """Return a stripped string; empty strings and None mean unknown."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _as_number(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered in {"1", "true", "on"}:
            return True
        if lowered in {"0", "false", "off"}:
            return False
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _parse_compact_utc(value: Any) -> datetime | None:
    """Parse the SmartHome compact ``YYYYMMDDTHHMMSSZ`` timestamp."""
    text = _as_text(value)
    if text is None or not text.endswith("Z"):
        return None
    try:
        return datetime.strptime(text, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def _empty_state(device: DeviceContext) -> Mapping[str, Any]:
    del device
    return {}


# ---------------------------------------------------------------------------
# Read-only entities
# ---------------------------------------------------------------------------


def _online_spec() -> EntitySpec:
    """Report router reachability even while the device is offline.

    The default availability would turn this entity into ``unavailable``
    when the router goes offline, hiding the very state automations need.
    """

    def state(device: DeviceContext) -> Mapping[str, Any]:
        return {"is_on": bool(device.available)}

    return EntitySpec(
        platform="binary_sensor",
        key="online",
        name="在线状态",
        state=state,
        metadata={"device_class": "connectivity"},
        availability=lambda _device: True,
    )


def _wifi_specs(context: DeviceContext) -> list[EntitySpec]:
    if not context.has_service(_SID_STS):
        return []

    def ssid_state(device: DeviceContext) -> Mapping[str, Any]:
        return {"native_value": _as_text(device.value(_SID_STS, "SSID"))}

    def bssid_state(device: DeviceContext) -> Mapping[str, Any]:
        return {"native_value": _as_text(device.value(_SID_STS, "BSSID"))}

    return [
        EntitySpec(
            platform="sensor",
            key="wifi_ssid",
            name="Wi-Fi SSID",
            state=ssid_state,
            metadata={"entity_category": "diagnostic"},
        ),
        EntitySpec(
            platform="sensor",
            key="wifi_bssid",
            name="Wi-Fi BSSID",
            state=bssid_state,
            metadata={"entity_category": "diagnostic"},
        ),
    ]


def _weekly_specs(context: DeviceContext) -> list[EntitySpec]:
    if not context.has_service(_SID_WEEKLY):
        return []

    def device_count_state(device: DeviceContext) -> Mapping[str, Any]:
        # flow/maxSpeed units are unconfirmed, so expose them raw only.
        return {
            "native_value": _as_int(device.value(_SID_WEEKLY, "deviceNum")),
            "extra_state_attributes": {
                "report_time_raw": _as_text(
                    device.value(_SID_WEEKLY, "time")
                ),
                "flow_raw": _as_number(
                    device.value(_SID_WEEKLY, "flow")
                ),
                "max_speed_raw": _as_number(
                    device.value(_SID_WEEKLY, "maxSpeed")
                ),
                "report_enabled": _as_bool(
                    device.value(_SID_WEEKLY, "enable")
                ),
            },
        }

    def enabled_state(device: DeviceContext) -> Mapping[str, Any]:
        return {"is_on": _as_bool(device.value(_SID_WEEKLY, "enable"))}

    def report_time_state(device: DeviceContext) -> Mapping[str, Any]:
        return {
            "native_value": _parse_compact_utc(
                device.value(_SID_WEEKLY, "time")
            )
        }

    return [
        EntitySpec(
            platform="sensor",
            key="weekly_device_count",
            name="本周接入设备数",
            state=device_count_state,
            metadata={"unit": "台", "state_class": "measurement"},
        ),
        EntitySpec(
            platform="binary_sensor",
            key="weekly_report_enabled",
            name="运行周报已开启",
            state=enabled_state,
            metadata={"entity_category": "diagnostic"},
        ),
        EntitySpec(
            platform="sensor",
            key="weekly_report_time",
            name="周报生成时间",
            state=report_time_state,
            metadata={
                "device_class": "timestamp",
                "entity_category": "diagnostic",
            },
        ),
    ]


def _auto_update_state(device: DeviceContext) -> Mapping[str, Any]:
    return {
        "is_on": _as_bool(device.value(_SID_UPDATE, "autoUpdateOn"))
    }


def _update_specs(context: DeviceContext) -> list[EntitySpec]:
    if not context.has_service(_SID_UPDATE):
        return []

    def firmware_state(device: DeviceContext) -> Mapping[str, Any]:
        attributes: dict[str, Any] = {}
        progress = _as_int(device.value(_SID_UPDATE, "progress"))
        if progress is not None:
            attributes["progress"] = progress
        introduction = _as_text(
            device.value(_SID_UPDATE, "introduction")
        )
        if introduction is not None:
            attributes["introduction"] = introduction
        auto_update = _as_bool(
            device.value(_SID_UPDATE, "autoUpdateOn")
        )
        if auto_update is not None:
            attributes["auto_update_on"] = auto_update
        action = _as_int(device.value(_SID_UPDATE, "action"))
        if action is not None:
            attributes["action_raw"] = action
        return {
            "native_value": _as_text(device.value(_SID_UPDATE, "version")),
            "extra_state_attributes": attributes or None,
        }

    specs = [
        EntitySpec(
            platform="sensor",
            key="firmware_version",
            name="固件版本",
            state=firmware_state,
            metadata={"entity_category": "diagnostic"},
        )
    ]

    specs.append(
        EntitySpec(
            platform="binary_sensor",
            key="auto_update_enabled",
            name="自动更新固件",
            state=_auto_update_state,
            metadata={"entity_category": "diagnostic"},
        )
    )
    return specs


# ---------------------------------------------------------------------------
# Push events (read-only)
# ---------------------------------------------------------------------------


def _device_access_decoder(
    device: DeviceContext,
    sid: str,
    data: Mapping[str, Any],
    timestamp: str | None,
) -> list[tuple[str, Mapping[str, Any]]]:
    """Turn one ``deviceAccess`` push into a Home Assistant event."""
    del device
    if sid != _SID_DEVICE_ACCESS:
        return []
    if not any(
        data.get(field) not in (None, "")
        for field in ("name", "time", "mac", "identifyId")
    ):
        return []
    return [
        (
            "device_access",
            {
                "device_name": _as_text(data.get("name")),
                "event_time": _as_text(data.get("time")),
                "type": data.get("type"),
                "mac": _as_text(data.get("mac")),
                "identify_id": _as_text(data.get("identifyId")),
                "push_type": _as_text(data.get("pushType")),
                "received_at": timestamp,
            },
        )
    ]


def _child_push_decoder(
    device: DeviceContext,
    sid: str,
    data: Mapping[str, Any],
    timestamp: str | None,
) -> list[tuple[str, Mapping[str, Any]]]:
    """Turn one ``childPush`` push into a Home Assistant event."""
    del device
    if sid != _SID_CHILD_PUSH:
        return []
    if not any(
        data.get(field) not in (None, "")
        for field in ("name", "time", "mac", "identityId")
    ):
        return []
    return [
        (
            "child_push",
            {
                "device_name": _as_text(data.get("name")),
                "event_time": _as_text(data.get("time")),
                "type": data.get("type"),
                "mac": _as_text(data.get("mac")),
                "identity_id": _as_text(data.get("identityId")),
                "push_type": _as_text(data.get("pushType")),
                "received_at": timestamp,
            },
        )
    ]


def _green_channel_decoder(
    device: DeviceContext,
    sid: str,
    data: Mapping[str, Any],
    timestamp: str | None,
) -> list[tuple[str, Mapping[str, Any]]]:
    """Turn one ``GreenChnJoin`` push into a Home Assistant event."""
    del device
    if sid != _SID_GREEN_CHANNEL:
        return []
    if not any(
        data.get(field) not in (None, "")
        for field in ("name", "mac")
    ):
        return []
    return [
        (
            "green_channel_join",
            {
                "device_name": _as_text(data.get("name")),
                "mac": _as_text(data.get("mac")),
                "received_at": timestamp,
            },
        )
    ]


def _event_specs(context: DeviceContext) -> list[EntitySpec]:
    specs: list[EntitySpec] = []
    if context.has_service(_SID_DEVICE_ACCESS):
        specs.append(
            EntitySpec(
                platform="event",
                key="device_access_event",
                name="设备接入事件",
                state=_empty_state,
                metadata={"event_types": ["device_access"]},
                event_decoder=_device_access_decoder,
            )
        )
    if context.has_service(_SID_CHILD_PUSH):
        specs.append(
            EntitySpec(
                platform="event",
                key="child_push_event",
                name="子设备接入推送",
                state=_empty_state,
                metadata={"event_types": ["child_push"]},
                event_decoder=_child_push_decoder,
            )
        )
    if context.has_service(_SID_GREEN_CHANNEL):
        specs.append(
            EntitySpec(
                platform="event",
                key="green_channel_event",
                name="绿色通道接入",
                state=_empty_state,
                metadata={"event_types": ["green_channel_join"]},
                event_decoder=_green_channel_decoder,
            )
        )
    return specs


# ---------------------------------------------------------------------------
# UNVERIFIED controls (disabled by default)
# ---------------------------------------------------------------------------


class ProductK10HAdapter:
    """华为路由 AX3 Pro (K10H / WS7200-10) read-only adapter."""

    prod_id = _PROD_ID

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None:
            return ()

        specs: list[EntitySpec] = [_online_spec()]
        specs.extend(_wifi_specs(context))
        specs.extend(_weekly_specs(context))
        specs.extend(_update_specs(context))
        specs.extend(_event_specs(context))
        return tuple(specs)


ADAPTER = ProductK10HAdapter()

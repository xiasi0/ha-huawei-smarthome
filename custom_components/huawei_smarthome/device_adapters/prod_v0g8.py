"""Product adapter for the HUAWEI Vision 6 smart screen (V0G8, NYHS-380P).

This is a smart TV, not an IoT accessory: Huawei controls it through the
native app and there is **no vendor H5 bundle** for this product id (the
CDN answers 403 for ``h5_001``), so nothing here can be cross-checked
against the vendor UI.  Everything exposed below is therefore **read-only
passthrough** backed only by the Profile's own structure:

* ``devicestate.screenState`` — the one characteristic the Profile's
  ``quickmenu`` puts on the home card, with a closed enum
  (0 已熄屏 / 1 在线 / 2 离线).
* ``messageboard`` — the family message board (留言者/留言内容/留言回复).
  The characteristics carry the ``P`` permission, but the write payload
  (whether a reply needs ``id``, whether ``sender``/``message`` must be
  echoed back) cannot be verified without the vendor UI, so the adapter
  never sends anything and only surfaces the reported values as sensors.

Deliberately NOT exposed:

* ``remotecontrol`` — every characteristic is ``RG`` (read only).  The
  interesting one, ``switchState`` (智慧屏操控开关, enum 0/1), cannot be
  toggled from the cloud, and the rest of the service (access_token,
  ip_addr, mask, gateway_mac, controller_mac) is pairing/diagnostic
  internals with no user value in Home Assistant.
* ``generalcommand`` — a free-form 2 KB string channel (发送/接收通用消息).
  The command grammar (key events? JSON?) is undocumented and there is no
  H5 sample to copy; a guessed payload could trigger arbitrary behaviour
  on the TV, so it stays out.
* ``autoconfig.hms_login_info`` — HMS login credential material, app-side.
* ``logreport`` — fault/ticket diagnostics (提单), app-side.
* ``version`` fields — diagnostics, consistent with the other adapters.
* ``messageboard.id`` (留言索引) — a bookkeeping counter, not user facing.
"""

from __future__ import annotations

from typing import Any, Mapping

from .api import EntitySpec
from .context import DeviceContext

_DEVICE_STATE_SID = "devicestate"
_SCREEN_STATE_FIELD = "screenState"

# Profile enumList of devicestate.screenState: closed set of three states.
# The cloud may report the raw value as int or as the Profile's string form.
_SCREEN_STATE_LABELS = {
    0: "已熄屏",
    1: "在线",
    2: "离线",
}

_MESSAGEBOARD_SID = "messageboard"
_MESSAGE_FIELDS = (
    # (field, entity key, entity name, Profile desc for the comment)
    ("sender", "message_sender", "留言者昵称"),  # sender
    ("message", "latest_message", "最新留言"),  # message
    ("reply", "message_reply", "留言回复"),  # reply
)


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


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _screen_state(context: DeviceContext) -> str | None:
    raw = context.value(_DEVICE_STATE_SID, _SCREEN_STATE_FIELD)
    if raw is None:
        return None
    try:
        number = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return _SCREEN_STATE_LABELS.get(number)


class ProductV0G8Adapter:
    """Read-only adapter for the HUAWEI Vision 6 smart screen (V0G8)."""

    prod_id = "V0G8"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        entities: list[EntitySpec] = []

        # --- screen state (the quickmenu home card) ----------------------
        if context.has_service(_DEVICE_STATE_SID) and _field(
            profile, _DEVICE_STATE_SID, _SCREEN_STATE_FIELD
        ) is not None:
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="screen_state",
                    name="屏幕状态",
                    state=lambda ctx: {"native_value": _screen_state(ctx)},
                    metadata={},
                )
            )

        # --- message board: read-only passthrough ------------------------
        if context.has_service(_MESSAGEBOARD_SID):
            for field, key, name in _MESSAGE_FIELDS:
                if _field(profile, _MESSAGEBOARD_SID, field) is None:
                    continue

                def _message_state(
                    ctx: DeviceContext, _fname: str = field
                ) -> dict[str, Any]:
                    return {"native_value": _text(ctx.value(_MESSAGEBOARD_SID, _fname))}

                entities.append(
                    EntitySpec(
                        platform="sensor",
                        key=key,
                        name=name,
                        state=_message_state,
                        metadata={},
                    )
                )

        return tuple(entities)


ADAPTER = ProductV0G8Adapter()

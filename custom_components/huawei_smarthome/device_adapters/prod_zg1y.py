"""User-contributed protocol for Huawei product ZG1Y.

Device: 华为 AI 超感传感器 / AI human presence sensor (deviceModel ``BER-SE10``,
deviceTypeId ``A14``).
Profile: https://smarthome-drcn.dbankcdn.com/device/guide/ZG1Y/ZG1Y.json

Exposed entities:

* ``sensor``        "光照度"             <- ``luminance.current``   (unit ``lx``)
* ``sensor``        "光照度等级"         <- ``luminance.level``     (1..6, 中文标签)
* ``sensor``        "接入方式"           <- 设备描述符的 ``prot_type`` / ``gateway_id``
* ``binary_sensor`` "总区域人员存在"     <- ``basicFenceEvent.existent``
* ``binary_sensor`` "区域N·<名称>人员存在" <- ``userFenceEvent<N>.existent``,
                                          N = 1..6, 名称来自 ``userFenceN.fenceName``
* ``switch``        "抗干扰增强"         <- ``basicFence.advancedPara`` bit 0
* ``switch``        "防宠检测"           <- ``basicFence.advancedPara`` bit 5
* ``switch``        "起夜检测"           <- ``basicFence.nightLightIndicationEnable``
* ``switch``        "安防检测"           <- ``basicFence.acrossEnable``
* ``switch``        "传感器检测"         <- ``switch.on``
* ``switch``        "电源开关"           <- ``switch.reportSwitch``
* ``switch``        "LED指示灯"          <- ``backlight.on``
* ``select``        "灵敏度"             <- ``basicFence.sensitivity``
                                          (高 2 / 中 3 / 低 4，H5
                                          ``chooseSensitivity``；未配置 1 /
                                          无效 0 保留在选项里兜底)
* ``select``        "人员定位"           <- ``basicFence.singleReport``
                                          (关 0 / 持续开启 1 / 开启三分钟 2，
                                          H5 首页 personPosition 单元格与
                                          安装/编辑页；提示文案与 Profile
                                          枚举互证)
* ``number``        "可感应最小目标高度" <- ``basicFence.filteringHeight``
                                          (0-70 cm，H5 ``setMinHeight``，
                                          行标签 min_height)
* ``button``        "重置无人状态"       <- ``action.action`` = 1
* ``button``        "重启设备"           <- ``reboot.action`` = 0 (Wi-Fi 接入时)

Field semantics were verified against the Profile, the vendor H5 page
(``h5_001/static/js/app.<hash>.js``) and a real device.  The bundle renders
``luminance.current + "lux"`` and maps ``levelText[luminance.level]`` to
暗光/弱光/适中/较强/强/很强; its region helper resolves ``fenceId`` 0 to
``basicFenceEvent`` and 1..6 to ``userFenceEvent1..6``.  Illuminance
201 lx / level 适中 was confirmed on hardware.

Deliberately *not* exposed (re-verified against the vendor bundle):

* ``luminance.threshold`` (RW 50-200) — the only ``threshold`` hits in the
  bundle belong to the bundled scroll library; the vendor UI never reads or
  writes the field, so its semantics have no second source.
* ``faultDetection.status`` / ``code`` — zero references in the bundle.
* ``basicFence.enableFence`` / ``standingExistentEnable`` /
  ``userFenceN.enableFence`` etc. — written only by the install wizard as
  part of a whole-fence configuration blob ({sensitivity: t, enableFence: 1}),
  never as a standalone toggle.
* ``devLocation`` — installation geometry (azimuth/height/坐标) maintained by
  the install wizard through composite strings (``installCoord``) that the
  Profile does not even declare.
* ``basicFenceEvent.standingExistent`` / ``across`` / ``nonBedStatus`` /
  ``acrossFence`` and ``postionTag`` / ``postionList`` — event details that
  only appear in the bundle's default-state blob and the App native history
  page's image map, never in live H5 UI.
* ``update`` / ``netInfo`` — OTA and read-only diagnostics, consistent with
  the other adapters.
* ``action`` values other than 1 (恢复出厂 / 擦除配置 / 解除绑定) are
  destructive and are not offered as buttons.

Presence is reported exactly as the device sends it: no local de-bounce and no
occupancy hold time is applied, so ``existent`` may flap on brief
mis-detections.  Keep any on/off delay in the automation or in a HA
``derivative``/``history_stats`` helper rather than here.

The switches and the two buttons were derived from the H5 handlers:

* ``basicFence.advancedPara`` is a 32-bit settings mask.  The bundle declares
  ``Y = 2, z = 32`` and reads it with ``J(mask, i) = (mask >> i) & 1``, turning
  it back into a number with ``parseInt(binary, 2)``.  The two switches are
  ``antijammingSwitch = J(mask, 0)`` and ``petSwitch = J(mask, 5)``; both
  handlers write the whole mask back (``V(mask, i, true)`` toggles bit ``i``)
  and the row is hidden while the mask is the ``-1`` "not reported" sentinel.
  Because a single mask carries unrelated settings and capability bits
  (24 = backup, 25 = pets support, 27 = fall detection, 29 = Wi-Fi signal),
  this adapter always re-derives the new mask from the mask the device last
  reported and never from a default of its own.
* ``起夜检测`` / ``安防检测`` are plain ``basicFence`` flags; the Profile calls
  them 起夜检测开关 / 安防检测开关 and the H5 sends ``0``/``1`` (not a JSON
  boolean) for both.
* ``LED指示灯`` is its own ``backlight`` service, *not* one of the
  ``advancedPara`` mask bits: the H5 writes
  ``setDeviceInfo({data:{backlight:{on: Number(!backlight.on)}}})`` and reads
  it back as ``Number(data.on)``, so the payload here is an explicit ``0``
  or ``1`` on ``backlight.on``.  The H5 only uses the lamp as an install aid
  (it lights it up while a zone is being edited and turns it off on the way
  out, warning "指示灯已开启，3分钟后自动关闭"), so this adapter exposes the
  plain flag and does not reproduce that flow.  The H5 also greys the row out
  unless ``reportSwitch && switchOn``; that is a UI shortcut, not a protocol
  limit, so no such gate is applied to a persistent entity.
* ``传感器检测`` / ``电源开关`` are the two ``0``/``1`` flags of the ``switch``
  service (传感器检测开关 / 事件上报开关).  ``电源开关`` is the Profile's
  ``reportSwitch``; it is named after the role it actually plays, because the
  vendor bundle drives only one of the two per product generation: it computes
  ``isOldDevice = (prodId === "ZG0F")`` and, for every other product including
  ZG1Y, its one big sensor switch writes *only*
  ``{switch: {reportSwitch: Number(!reportSwitch)}}``.  So on ZG1Y that field
  is the device's main power switch, while ``switch.on`` is the one the bundle
  never writes.  ``switch.on`` is still reported by the device and declared
  ``RW`` in the Profile, so it stays exposed side by side; this adapter sends
  the same ``0``/``1`` shape its sibling on the same service uses.  Which of
  the two really gates sensing is worth confirming on hardware.
* ``重启设备`` reproduces the H5's ``rebootClick``, which branches on the access
  type: a Wi-Fi device is restarted with ``{reboot: {action: 0}}`` (重启本设备),
  while a device behind a gateway uses
  ``{reboot: {action: 2, devList: [{sn: deviceSn}]}}``.  The integration has no
  serial number to put into ``devList``, and ``action: 0`` on a
  gateway-attached device would risk restarting the gateway instead, so the
  button is only created while the cloud reports a Wi-Fi protocol type.
* ``重置无人状态`` sends ``{"action": {"action": 1}}``, matching the Profile
  enum ``1 = 重置传感器无人状态``.  The H5 wording for the payload is
  ``resetNoMan`` -> ``setDeviceInfo({data:{action:{action:1}}})``.
* ``接入方式`` is not a service at all.  The H5 derives it from the device
  descriptor: ``protType == "1"`` is Wi-Fi (direct when ``gatewayId == devId``,
  through a hub otherwise) and ``"5"``/``"11"`` is PLC.  The descriptor's
  ``protocol_type`` / ``gateway_id`` carry exactly those cloud fields, so the
  same rule is reproduced here.  Note this is *not* the Profile's top level
  ``protocolType`` (``softApPin``), which describes pairing instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_ILLUMINANCE_SID = "luminance"
_ILLUMINANCE_FIELD = "current"
_LEVEL_FIELD = "level"

# The Profile declares no unit for ``luminance.current``.  The vendor H5 page
# appends "lux" when displaying it, so the raw value is already in lx and must
# not be rescaled.  Change this single constant if a real device disagrees.
_ILLUMINANCE_UNIT = "lx"

# Fallback only: the labels are normally read from the Profile ``enumList``.
_LEVEL_LABELS = ("暗光", "弱光", "适中", "较强", "强", "很强")

_BASIC_FENCE_EVENT_SID = "basicFenceEvent"
_USER_FENCE_SIDS = tuple(f"userFence{index}" for index in range(1, 7))
_USER_FENCE_EVENT_SIDS = tuple(
    f"userFenceEvent{index}" for index in range(1, 7)
)
_FENCE_NAME_FIELD = "fenceName"
_EXISTENT_FIELD = "existent"

# ``occupancy`` predates ``presence`` and is available on every supported HA
# Core release; it maps on = 有人占用.
_PRESENCE_DEVICE_CLASS = "occupancy"

_BASIC_FENCE_SID = "basicFence"
_ADVANCED_PARA_FIELD = "advancedPara"
_NIGHT_LIGHT_FIELD = "nightLightIndicationEnable"
_ACROSS_FIELD = "acrossEnable"

# LED indicator: a service of its own, unrelated to the advancedPara mask.
_BACKLIGHT_SID = "backlight"
_BACKLIGHT_FIELD = "on"

# 传感器开关: two independent 0/1 flags on their own service.
_SWITCH_SID = "switch"
_SENSOR_ON_FIELD = "on"
_EVENT_REPORT_FIELD = "reportSwitch"

_REBOOT_SID = "reboot"
_REBOOT_ACTION_FIELD = "action"
# Profile enumList: 0 重启本设备, 1 重启所有设备, 2 批量重启网关本身和部分子设备,
# 3 批量重启子设备.  An entity that stands for one device only ever means
# that device, which is also the branch the H5 takes for Wi-Fi devices.
_REBOOT_THIS_DEVICE = 0

# Every plain 0/1 flag switch, as (service, field, entity key, entity name).
# 起夜检测 / 安防检测 live on ``basicFence``, 传感器检测 / 电源开关 on the
# ``switch`` service and LED指示灯 on ``backlight``; they all share one payload
# shape, so they share one loop and one factory.
#
# ``event_report`` keeps its original key on purpose: the key becomes the
# entity's unique_id, so renaming it would orphan the entry in the registry and
# hand the user a second, empty switch next to the one already on their
# dashboard.  Only the display name follows the device.
_FLAG_SWITCHES = (
    (_BASIC_FENCE_SID, _NIGHT_LIGHT_FIELD, "night_light_indication", "起夜检测"),
    (_BASIC_FENCE_SID, _ACROSS_FIELD, "across_detection", "安防检测"),
    (_SWITCH_SID, _SENSOR_ON_FIELD, "sensor_detection", "传感器检测"),
    (_SWITCH_SID, _EVENT_REPORT_FIELD, "event_report", "电源开关"),
    (_BACKLIGHT_SID, _BACKLIGHT_FIELD, "backlight", "LED指示灯"),
)

# ``basicFence.advancedPara`` is a 32-bit settings bitmask.  The vendor H5
# bundle reads it with ``J(mask, i) = (mask >> i) & 1`` and writes it back as a
# whole number, so bit indices below are the bundle's own.
_ANTIJAMMING_BIT = 0
_PETS_DETECTION_BIT = 5
# The H5 gates the pets row on ``uv(mask, 25)``.  A created entity cannot be
# hidden afterwards, so the reader reports unknown while this bit is clear.
_PETS_DETECTION_SUPPORT_BIT = 25
# The bundle treats -1 as "not reported / unsupported" for this field.
_ADVANCED_PARA_UNKNOWN = -1

_ACTION_SID = "action"
_ACTION_FIELD = "action"
# Profile enumList: 0 无效, 1 重置传感器无人状态, 2 恢复出厂, 3 上报配置参数.
_RESET_NO_PRESENCE = 1

# 接入方式, exactly the vendor H5's ``Zl`` list indexed by its ``netMode``.
_ACCESS_MODE_PLC = "PLC接入"
_ACCESS_MODE_WIFI_HUB = "WiFi中枢接入"
_ACCESS_MODE_WIFI_DIRECT = "WiFi直连接入"
_WIFI_PROTOCOL_TYPE = "1"
_PLC_PROTOCOL_TYPES = frozenset({"5", "11"})

# 灵敏度.  The vendor picker (``chooseSensitivity``) offers 高/中/低 =
# 2/3/4 (matching the Profile enumList) and dispatches
# ``{basicFence: {sensitivity: value}}``.  The two placeholder values stay
# in the option list so a device reporting them still resolves to a label.
_SENSITIVITY_FIELD = "sensitivity"
_SENSITIVITY_OPTIONS = (
    (2, "高"),
    (3, "中"),
    (4, "低"),
    (1, "未配置"),
    (0, "无效/不支持"),
)

# 人员定位.  The home cell (personPosition 人员定位) toggles
# ``{basicFence: {singleReport: on ? 0 : 2}}`` and its tip reads
# 开启后，区域图内将展示人的位置（配置区域时自动开启）；再次点击即可
# 关闭，或 3分钟后自动关闭, matching the Profile enum 0 关 / 1 持续开 /
# 2 持续打开三分钟; the install/edit pages send 0/1/2 directly.
_PERSON_POSITION_FIELD = "singleReport"
_PERSON_POSITION_OPTIONS = ((0, "关"), (1, "持续开启"), (2, "开启三分钟"))

# 可感应最小目标高度.  ``setMinHeight`` dispatches
# ``{basicFence: {filteringHeight: t}}`` and the row label is
# min_height 可感应最小目标高度 (cm); the Profile range is 0..70.
_MIN_HEIGHT_FIELD = "filteringHeight"


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
        if not isinstance(field, Mapping):
            continue
        if field.get("characteristicName") == name:
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


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, (Mapping, list, tuple, set)):
        return None
    text = str(value).strip()
    return text or None


def _level_labels(profile: Mapping[str, Any]) -> dict[int, str]:
    """Map ``luminance.level`` to its label from the Profile ``enumList``."""

    labels: dict[int, str] = {}
    field = _field(profile, _ILLUMINANCE_SID, _LEVEL_FIELD)
    for option in (field or {}).get("enumList", ()):
        if not isinstance(option, Mapping):
            continue
        level = _number(option.get("enumVal"))
        label = _text(option.get("descCh"))
        if level is None or label is None:
            continue
        labels[int(level)] = label
    if labels:
        return labels
    return dict(enumerate(_LEVEL_LABELS, start=1))


def _illuminance_state(context: DeviceContext) -> Mapping[str, Any]:
    return {
        "native_value": _number(
            context.value(_ILLUMINANCE_SID, _ILLUMINANCE_FIELD)
        )
    }


def _presence_state(event_sid: str):
    """Build a reader for one region.

    The reader is a factory because a ``for`` loop over ``lambda`` closures
    would otherwise capture the last ``event_sid`` for every region.
    """

    def state(context: DeviceContext) -> Mapping[str, Any]:
        return {"is_on": _bool(context.value(event_sid, _EXISTENT_FIELD))}

    return state


def _advanced_para(context: DeviceContext) -> int | None:
    """Read the ``basicFence.advancedPara`` bitmask.

    Returns ``None`` while the device has not reported one, so callers can keep
    the state unknown instead of assuming a mask.
    """

    value = _number(context.value(_BASIC_FENCE_SID, _ADVANCED_PARA_FIELD))
    if value is None:
        return None
    mask = int(value)
    return None if mask == _ADVANCED_PARA_UNKNOWN else mask


def _mask_bit_state(bit: int, support_bit: int | None = None):
    """Build a switch reader for one ``advancedPara`` bit.

    ``support_bit`` is the capability bit the H5 gates the row on.  Entities
    are created once and cannot be hidden later, so a cleared capability bit
    reports unknown instead of a misleading "off".
    """

    def state(context: DeviceContext) -> Mapping[str, Any]:
        mask = _advanced_para(context)
        if mask is None:
            return {"is_on": None}
        if support_bit is not None and not (mask >> support_bit) & 1:
            return {"is_on": None}
        return {"is_on": bool((mask >> bit) & 1)}

    return state


def _mask_bit_action(bit: int, value: bool):
    """Build a switch command that sets one ``advancedPara`` bit.

    The vendor H5 flips the bit it just read.  HA delivers explicit on/off
    requests instead, so the bit is set rather than toggled, but the base is
    still the mask the device last reported: this one field also carries
    capability and unrelated settings bits, so inventing a default here could
    silently disable them.

    Unlike the reader this deliberately ignores the capability bit: the whole
    payload is harmless if the bit turns out to be unsupported, whereas
    refusing to send would break the control if the bit's meaning were ever
    misread.
    """

    async def action(
        context: DeviceContext,
        _data: Mapping[str, Any],
    ) -> None:
        mask = _advanced_para(context)
        if mask is None:
            raise ValueError(
                "ZG1Y basicFence.advancedPara has not been reported yet"
            )
        new_mask = mask | (1 << bit) if value else mask & ~(1 << bit)
        await context.async_send_service(
            _BASIC_FENCE_SID,
            {_ADVANCED_PARA_FIELD: new_mask},
        )

    return action


def _flag_state(sid: str, field: str):
    """Build a switch reader for a plain boolean flag on any service."""

    def state(context: DeviceContext) -> Mapping[str, Any]:
        return {"is_on": _bool(context.value(sid, field))}

    return state


def _flag_action(sid: str, field: str, value: int):
    """Build a switch command for a plain boolean flag on any service.

    The H5 sends ``0``/``1`` for these fields rather than a JSON boolean, so
    the payload keeps that form.
    """

    async def action(
        context: DeviceContext,
        _data: Mapping[str, Any],
    ) -> None:
        await context.async_send_service(sid, {field: value})

    return action


def _flag_switch(sid: str, field: str, key: str, name: str) -> EntitySpec:
    """Build one plain 0/1 flag switch from the ``_FLAG_SWITCHES`` table."""

    return EntitySpec(
        platform="switch",
        key=key,
        name=name,
        state=_flag_state(sid, field),
        actions={
            "turn_on": _flag_action(sid, field, 1),
            "turn_off": _flag_action(sid, field, 0),
        },
    )


async def _reset_no_presence(
    context: DeviceContext,
    _data: Mapping[str, Any],
) -> None:
    """Force a "no one present" report, as ``resetNoMan`` does in the H5."""

    await context.async_send_service(
        _ACTION_SID,
        {_ACTION_FIELD: _RESET_NO_PRESENCE},
    )


async def _reboot_device(
    context: DeviceContext,
    _data: Mapping[str, Any],
) -> None:
    """Restart this device, as ``rebootClick`` does in the H5 over Wi-Fi.

    Only reachable while the device is reported as Wi-Fi attached; see
    ``_uses_wifi`` for why the gateway branch is not reproduced.
    """

    await context.async_send_service(
        _REBOOT_SID,
        {_REBOOT_ACTION_FIELD: _REBOOT_THIS_DEVICE},
    )


def _no_state(_context: DeviceContext) -> Mapping[str, Any]:
    """Buttons carry no state, but ``EntitySpec`` still wants a reader."""

    return {}


def _access_mode(context: DeviceContext) -> str | None:
    """Describe how the device reaches the cloud, as the H5 does.

    Reproduces ``Zl[netMode]`` from the vendor bundle.  The descriptor's
    ``protocol_type`` and ``gateway_id`` are the cloud's ``protType`` and
    ``gatewayId``, the two fields the H5 rule reads.
    """

    protocol = _text(context.descriptor.protocol_type)
    if protocol is None:
        return None
    if protocol == _WIFI_PROTOCOL_TYPE:
        gateway = _text(context.descriptor.gateway_id) or ""
        device = _text(context.descriptor.dev_id) or ""
        # A device that is its own gateway is attached directly, otherwise it
        # hangs off a hub.
        if gateway == device:
            return _ACCESS_MODE_WIFI_DIRECT
        return _ACCESS_MODE_WIFI_HUB
    if protocol in _PLC_PROTOCOL_TYPES:
        return _ACCESS_MODE_PLC
    # Same fallback as the H5: show whatever the cloud reported.
    return protocol


def _access_mode_state(context: DeviceContext) -> Mapping[str, Any]:
    return {"native_value": _access_mode(context)}


def _uses_wifi(context: DeviceContext) -> bool:
    """Whether the cloud reaches this device directly over Wi-Fi.

    Mirrors the H5's ``isWifi = netMode !== PLC``.  The reboot payload differs
    between the two kinds of attachment: a Wi-Fi device is restarted with
    ``reboot.action = 0``, whereas a gateway-attached one needs ``action = 2``
    plus a ``devList`` of serial numbers the integration cannot supply.
    """

    return _text(context.descriptor.protocol_type) == _WIFI_PROTOCOL_TYPE


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _enum_select(
    profile: Mapping[str, Any],
    sid: str,
    field: str,
    key: str,
    name: str,
    options: tuple[tuple[int, str], ...],
) -> EntitySpec | None:
    """Build a ``select`` over one enum characteristic.

    ``options`` is the full value/label table, placeholders included, so a
    reported placeholder still resolves to its label.  Unknown values map to
    unknown instead of an invented option.
    """

    if _field(profile, sid, field) is None:
        return None
    labels = {value: label for value, label in options}
    values = {label: value for value, label in options}

    def state(context: DeviceContext) -> Mapping[str, Any]:
        number = _number(context.value(sid, field))
        if number is None:
            return {"current_option": None}
        return {"current_option": labels.get(int(number))}

    async def action(context: DeviceContext, data: Mapping[str, Any]) -> None:
        option = data["option"]
        if option not in values:
            raise ValueError(f"{key}: unknown option {option!r}")
        await context.async_send_service(sid, {field: values[option]})

    return EntitySpec(
        platform="select",
        key=key,
        name=name,
        state=state,
        metadata={"options": [label for _, label in options]},
        actions={"select_option": action},
    )


def _min_height_number(profile: Mapping[str, Any]) -> EntitySpec | None:
    """可感应最小目标高度 (``basicFence.filteringHeight``, cm)."""

    if _field(profile, _BASIC_FENCE_SID, _MIN_HEIGHT_FIELD) is None:
        return None

    def state(context: DeviceContext) -> Mapping[str, Any]:
        value = _number(context.value(_BASIC_FENCE_SID, _MIN_HEIGHT_FIELD))
        if value is None:
            return {"native_value": None}
        return {"native_value": _clamp(value, 0, 70)}

    async def action(context: DeviceContext, data: Mapping[str, Any]) -> None:
        value = _clamp(float(data["value"]), 0, 70)
        await context.async_send_service(
            _BASIC_FENCE_SID,
            {_MIN_HEIGHT_FIELD: round(value)},
        )

    return EntitySpec(
        platform="number",
        key="min_detectable_height",
        name="可感应最小目标高度",
        state=state,
        metadata={"min": 0, "max": 70, "step": 1, "unit": "cm"},
        actions={"set_value": action},
    )


class ProductZg1yAdapter:
    """Keep all ZG1Y entity choices in this file."""

    prod_id = "ZG1Y"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        entities: list[EntitySpec] = []

        if _field(profile, _ILLUMINANCE_SID, _ILLUMINANCE_FIELD) is not None:
            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="illuminance",
                    name="光照度",
                    state=_illuminance_state,
                    metadata={
                        "unit": _ILLUMINANCE_UNIT,
                        "device_class": "illuminance",
                        "state_class": "measurement",
                    },
                )
            )

        if _field(profile, _ILLUMINANCE_SID, _LEVEL_FIELD) is not None:
            labels = _level_labels(profile)

            def level_state(device: DeviceContext) -> Mapping[str, Any]:
                value = _number(device.value(_ILLUMINANCE_SID, _LEVEL_FIELD))
                if value is None:
                    return {"native_value": None}
                # An unmapped level stays unknown instead of inventing a label.
                return {"native_value": labels.get(int(value))}

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="illuminance_level",
                    name="光照度等级",
                    state=level_state,
                )
            )

        # The H5 shows the access mode row unconditionally, so it is not tied
        # to any service here either.
        entities.append(
            EntitySpec(
                platform="sensor",
                key="access_mode",
                name="接入方式",
                state=_access_mode_state,
            )
        )

        entities.extend(self._presence_entities(context))
        entities.extend(self._switch_entities(context, profile))

        # Config features on the basicFence service, each verified against a
        # vendor dispatch: 灵敏度 (chooseSensitivity), 人员定位
        # (personPosition cell toggle / install pages), 可感应最小目标高度
        # (setMinHeight).
        if context.has_service(_BASIC_FENCE_SID):
            for spec in (
                _enum_select(
                    profile,
                    _BASIC_FENCE_SID,
                    _SENSITIVITY_FIELD,
                    "sensitivity",
                    "灵敏度",
                    _SENSITIVITY_OPTIONS,
                ),
                _enum_select(
                    profile,
                    _BASIC_FENCE_SID,
                    _PERSON_POSITION_FIELD,
                    "person_position",
                    "人员定位",
                    _PERSON_POSITION_OPTIONS,
                ),
                _min_height_number(profile),
            ):
                if spec is not None:
                    entities.append(spec)

        if context.has_service(_ACTION_SID):
            entities.append(
                EntitySpec(
                    platform="button",
                    key="reset_no_presence",
                    name="重置无人状态",
                    state=_no_state,
                    actions={"press": _reset_no_presence},
                )
            )

        # Only over Wi-Fi: see ``_uses_wifi``.  A gateway-attached device would
        # need ``{action: 2, devList: [{sn}]}`` and the integration has no sn.
        if context.has_service(_REBOOT_SID) and _uses_wifi(context):
            entities.append(
                EntitySpec(
                    platform="button",
                    key="reboot",
                    name="重启设备",
                    state=_no_state,
                    actions={"press": _reboot_device},
                )
            )
        return tuple(entities)

    def _switch_entities(
        self,
        context: DeviceContext,
        profile: Mapping[str, Any],
    ) -> tuple[EntitySpec, ...]:
        """Every writable switch the device offers.

        Two families.  The ``advancedPara`` bit switches come first: that field
        is not declared in the Profile, so they are offered on the strength of
        the ``basicFence`` service alone and report unknown until the device
        sends a mask.  Everything else is a plain ``0``/``1`` flag listed in
        ``_FLAG_SWITCHES``, each gated on its own service and field, which is
        also why the LED indicator survives a device that does not expose
        ``basicFence`` at all.
        """

        entities: list[EntitySpec] = []

        if context.has_service(_BASIC_FENCE_SID):
            entities.extend(
                EntitySpec(
                    platform="switch",
                    key=key,
                    name=name,
                    state=_mask_bit_state(bit, support_bit),
                    actions={
                        "turn_on": _mask_bit_action(bit, True),
                        "turn_off": _mask_bit_action(bit, False),
                    },
                )
                for bit, support_bit, key, name in (
                    (_ANTIJAMMING_BIT, None, "antijamming", "抗干扰增强"),
                    (
                        _PETS_DETECTION_BIT,
                        _PETS_DETECTION_SUPPORT_BIT,
                        "pets_detection",
                        "防宠检测",
                    ),
                )
            )

        for sid, field, key, name in _FLAG_SWITCHES:
            if not context.has_service(sid):
                continue
            if _field(profile, sid, field) is None:
                continue
            entities.append(_flag_switch(sid, field, key, name))

        return tuple(entities)

    def _presence_entities(
        self,
        context: DeviceContext,
    ) -> tuple[EntitySpec, ...]:
        """One occupancy entity per region the device reports on.

        The region index (``userFenceEvent<N>``) is part of the entity name:
        several regions can share the same reported ``fenceName`` (factory
        placeholders such as "default"), so the name alone must stay
        unambiguous.
        """

        entities: list[EntitySpec] = []

        if context.has_service(_BASIC_FENCE_EVENT_SID):
            # The basic region is always the whole monitored area (总区域),
            # whatever it is called in the Huawei app; its reported fenceName
            # can be empty or a placeholder and would only add ambiguity.
            entities.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="presence_basic",
                    name="总区域人员存在",
                    state=_presence_state(_BASIC_FENCE_EVENT_SID),
                    metadata={"device_class": _PRESENCE_DEVICE_CLASS},
                )
            )

        for index, (fence_sid, event_sid) in enumerate(
            zip(_USER_FENCE_SIDS, _USER_FENCE_EVENT_SIDS),
            start=1,
        ):
            if not context.has_service(event_sid):
                continue
            # fenceName is whatever the user typed in the Huawei app and can
            # repeat ("default"), so prefix the stable region index.
            reported = _text(context.value(fence_sid, _FENCE_NAME_FIELD))
            entities.append(
                EntitySpec(
                    platform="binary_sensor",
                    key=f"presence_zone_{index}",
                    name=f"区域{index}·{reported or '未命名'}人员存在",
                    state=_presence_state(event_sid),
                    metadata={"device_class": _PRESENCE_DEVICE_CLASS},
                )
            )
        return tuple(entities)


ADAPTER = ProductZg1yAdapter()

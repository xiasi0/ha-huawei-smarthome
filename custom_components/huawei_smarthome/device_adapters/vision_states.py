"""Read-only fields observed on V0D5 and V0DE; never expose LAN credentials.

Only screenState enum labels come from each product's own Profile. Other codes
remain raw: picture-mode mappings measured on another panel do not apply here.
Cloud writes / generalcommand payloads have not been verified for these models.
"""

from .api import EntitySpec
from .context import DeviceContext
from .profile_fields import sensor


def entities(context: DeviceContext) -> tuple[EntitySpec, ...]:
    if context.profile is None:
        return ()
    fields = (
        ("screen_state", "屏幕状态", "devicestate", "screenState", "enum", {}),
        ("power_code", "电源状态码", "switch", "on", "number", {}),
        ("screen_on", "屏幕点亮", "screen", "on", "bool", {}),
        ("brightness", "屏幕亮度", "screen", "brightness", "number", {}),
        ("volume", "音量", "speaker", "volume", "number", {}),
        ("muted", "静音", "speaker", "mute", "bool", {}),
        ("input_source", "输入源", "inputSource", "name", "text", {}),
        ("picture_mode", "图像模式码", "pictureMode", "mode", "number", {}),
        ("system_mode", "系统模式", "systemMode", "mode", "text", {}),
    )
    return tuple(sensor(key, name, sid, attr, kind=kind, metadata=metadata)
                 for key, name, sid, attr, kind, metadata in fields
                 if context.has_service(sid))

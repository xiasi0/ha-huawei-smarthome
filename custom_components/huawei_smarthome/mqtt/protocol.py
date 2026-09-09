"""Decode the application-level Huawei SmartHome MQTT envelope."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True, slots=True)
class HuaweiMqttMessage:
    """One decoded SmartHome application message."""

    body: Mapping[str, Any]
    header: Mapping[str, Any]

    @property
    def notify_type(self) -> str | None:
        value = self.header.get("notifyType")
        return value if isinstance(value, str) else None


def decode_message(payload: bytes) -> HuaweiMqttMessage | None:
    """Decode a valid SmartHome JSON envelope, otherwise return ``None``."""

    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, Mapping):
        return None
    body = value.get("body")
    header = value.get("header")
    if not isinstance(body, Mapping) or not isinstance(header, Mapping):
        return None
    return HuaweiMqttMessage(body=body, header=header)


"""Single-service Huawei SmartHome MQTT command gateway."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any
import uuid

from ..const import OBSERVED_MQTT_FILTER
from ..errors import HuaweiSmartHomeError
from ..mqtt_client import HuaweiMqttClient
from .protocol import decode_message


COMMAND_ACK_TIMEOUT = 10.0


class HuaweiCommandRejectedError(HuaweiSmartHomeError):
    """The SmartHome cloud rejected a service command."""


class HuaweiCommandGateway:
    """Publish one service command and correlate its service ACK."""

    def __init__(
        self,
        mqtt: HuaweiMqttClient,
        *,
        timeout: float = COMMAND_ACK_TIMEOUT,
    ) -> None:
        if timeout <= 0:
            raise ValueError("command timeout must be positive")
        self._mqtt = mqtt
        self._timeout = timeout
        self._pending: dict[str, asyncio.Future[int]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def async_send(
        self,
        *,
        device_id: str,
        sid: str,
        body: Mapping[str, Any],
    ) -> None:
        """Send one ``sid`` command and wait for its cloud ACK."""

        if not device_id or not sid:
            raise ValueError("device_id and sid are required")
        target = f"/devices/{device_id}/services/{sid}"
        lock = self._locks.setdefault(target, asyncio.Lock())
        async with lock:
            request_id = str(uuid.uuid4()).upper()
            future = asyncio.get_running_loop().create_future()
            self._pending[target] = future
            try:
                await self._mqtt.async_publish_command(
                    topic=OBSERVED_MQTT_FILTER,
                    target=target,
                    body=dict(body),
                    request_id=request_id,
                )
                remote_code = await asyncio.wait_for(
                    future,
                    timeout=self._timeout,
                )
            finally:
                self._pending.pop(target, None)
            if remote_code != 0:
                raise HuaweiCommandRejectedError(
                    f"SmartHome command rejected: sid={sid} "
                    f"errcode={remote_code}"
                )

    def handle_message(self, payload: bytes) -> bool:
        """Resolve a pending command from one inbound MQTT payload."""

        message = decode_message(payload)
        if message is None or message.notify_type != "commandRsp":
            return False
        target = message.header.get("from")
        if not isinstance(target, str):
            return False
        future = self._pending.get(target)
        if future is None or future.done():
            return False
        try:
            remote_code = int(message.body.get("errcode", -1))
        except (TypeError, ValueError):
            remote_code = -1
        future.set_result(remote_code)
        return True

    def close(self) -> None:
        """Cancel pending commands owned by this gateway."""

        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()
        self._locks.clear()


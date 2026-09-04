"""Minimal Huawei SmartHome MQTT connection and subscription client."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
import logging
from typing import Any, Protocol

from .errors import HuaweiSmartHomeError
from .domain.models import ConnectionState, MqttConnectionSettings


_LOGGER = logging.getLogger(__name__)


class MqttConnectionError(HuaweiSmartHomeError):
    """The MQTT connection is unavailable."""


class MqttConfigurationError(HuaweiSmartHomeError):
    """The MQTT connection configuration is invalid."""


class MqttProtocolError(HuaweiSmartHomeError):
    """The MQTT broker rejected a protocol operation."""


MqttStateListener = Callable[[ConnectionState], Awaitable[None] | None]
MqttConnectionLostHandler = Callable[[], None]


class AsyncMqttTransport(Protocol):
    """Small transport boundary used by the MQTT client."""

    async def connect(self, settings: MqttConnectionSettings) -> None:
        """Connect to the broker."""

    async def subscribe(
        self,
        filters: Sequence[str],
        qos: int,
    ) -> None:
        """Subscribe to broker filters."""

    async def disconnect(self) -> None:
        """Disconnect from the broker."""

    def set_connection_lost_handler(
        self,
        handler: MqttConnectionLostHandler | None,
    ) -> None:
        """Set the unexpected-disconnect callback."""


class HuaweiMqttClient:
    """Own one MQTT connection and its subscription lifecycle."""

    def __init__(
        self,
        *,
        transport: AsyncMqttTransport | None = None,
        on_state_changed: MqttStateListener | None = None,
        connect_timeout: float = 20.0,
    ) -> None:
        if connect_timeout <= 0:
            raise ValueError("MQTT connect timeout must be positive")
        self._transport = transport or PahoMqttTransport(
            connect_timeout=connect_timeout,
        )
        self._on_state_changed = on_state_changed
        self._state = ConnectionState.STOPPED
        self._generation = 0
        self._settings: MqttConnectionSettings | None = None
        self._connection_lost = asyncio.Event()
        self._operation_lock = asyncio.Lock()
        self._stopping = False
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def state(self) -> ConnectionState:
        """Return the current MQTT state."""

        return self._state

    @property
    def generation(self) -> int:
        """Return the current connection generation."""

        return self._generation

    @property
    def settings(self) -> MqttConnectionSettings | None:
        """Return the active MQTT settings."""

        return self._settings

    async def async_start(self, settings: MqttConnectionSettings) -> None:
        """Connect and subscribe before exposing the client as running."""

        if not settings.broker_host or settings.broker_port <= 0:
            raise MqttConfigurationError("MQTT broker address is incomplete")
        if not settings.client_id:
            raise MqttConfigurationError("MQTT client id is missing")
        if not settings.subscription_filters:
            raise MqttConfigurationError("MQTT subscription filters are missing")
        if settings.subscription_qos not in {0, 1, 2}:
            raise MqttConfigurationError("MQTT subscription QoS is invalid")
        if settings.keepalive <= 0:
            raise MqttConfigurationError("MQTT keepalive is invalid")

        async with self._operation_lock:
            await self._stop_unlocked()
            self._generation += 1
            generation = self._generation
            self._settings = settings
            self._loop = asyncio.get_running_loop()
            self._stopping = False
            self._connection_lost.clear()
            self._transport.set_connection_lost_handler(
                self._mark_connection_lost
            )
            await self._set_state(ConnectionState.MQTT_CONNECTING)
            try:
                await self._transport.connect(settings)
                await self._set_state(ConnectionState.MQTT_SUBSCRIBING)
                await self._transport.subscribe(
                    settings.subscription_filters,
                    settings.subscription_qos,
                )
            except Exception as error:
                try:
                    await self._transport.disconnect()
                finally:
                    await self._set_state(ConnectionState.DEGRADED)
                    self._connection_lost.set()
                raise MqttConnectionError(
                    "Huawei SmartHome MQTT session failed to start"
                ) from error

            await self._set_state(ConnectionState.RUNNING)
            _LOGGER.debug(
                "Huawei SmartHome MQTT ready: generation=%s filters=%s",
                generation,
                settings.subscription_filters,
            )

    async def async_wait_connection_lost(self) -> None:
        """Wait for an unexpected connection loss."""

        await self._connection_lost.wait()

    async def async_stop(self) -> None:
        """Stop the MQTT client."""

        async with self._operation_lock:
            await self._stop_unlocked()

    async def _stop_unlocked(self) -> None:
        self._stopping = True
        try:
            await self._transport.disconnect()
        finally:
            self._connection_lost.set()
            self._settings = None
            self._loop = None
            await self._set_state(ConnectionState.STOPPED)

    def _mark_connection_lost(self) -> None:
        """Bridge a transport callback to the Home Assistant loop."""

        loop = self._loop
        if loop is None or loop.is_closed() or self._stopping:
            return
        loop.call_soon_threadsafe(self._handle_connection_lost)

    def _handle_connection_lost(self) -> None:
        """Mark the active generation as degraded."""

        if self._stopping or self._state is ConnectionState.STOPPED:
            return
        self._connection_lost.set()
        asyncio.create_task(self._set_state(ConnectionState.DEGRADED))

    async def _set_state(self, state: ConnectionState) -> None:
        if self._state is state:
            return
        self._state = state
        if self._on_state_changed is None:
            return
        result = self._on_state_changed(state)
        if asyncio.iscoroutine(result):
            await result


class PahoMqttTransport:
    """Paho MQTT 3.1.1 transport with no application message handler."""

    def __init__(self, *, connect_timeout: float = 20.0) -> None:
        self._connect_timeout = connect_timeout
        self._client: Any | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connected: asyncio.Event | None = None
        self._connect_error: BaseException | None = None
        self._connection_lost_handler: MqttConnectionLostHandler | None = None
        self._pending_subscriptions: dict[int, asyncio.Future[None]] = {}
        self._subscription_results: dict[int, BaseException | None] = {}

    async def connect(self, settings: MqttConnectionSettings) -> None:
        """Connect and wait for CONNACK."""

        import paho.mqtt.client as mqtt

        await self.disconnect()
        self._loop = asyncio.get_running_loop()
        self._connected = asyncio.Event()
        self._connect_error = None
        kwargs: dict[str, Any] = {
            "client_id": settings.client_id,
            "protocol": mqtt.MQTTv311,
            "callback_api_version": mqtt.CallbackAPIVersion.VERSION2,
        }
        if settings.clean_session is not None:
            kwargs["clean_session"] = settings.clean_session
        client = mqtt.Client(**kwargs)
        self._client = client
        if settings.username is not None:
            client.username_pw_set(settings.username, settings.password)
        if settings.use_tls:
            await asyncio.to_thread(client.tls_set)
        client.on_connect = self._on_connect
        client.on_connect_fail = self._on_connect_fail
        client.on_disconnect = self._on_disconnect
        client.on_subscribe = self._on_subscribe
        result = client.connect_async(
            settings.broker_host,
            settings.broker_port,
            settings.keepalive,
        )
        if result != mqtt.MQTT_ERR_SUCCESS:
            raise MqttConnectionError(
                f"MQTT connect_async returned {result}"
            )
        client.loop_start()
        try:
            await asyncio.wait_for(
                self._connected.wait(),
                timeout=self._connect_timeout,
            )
        except asyncio.TimeoutError as error:
            await self.disconnect()
            raise MqttConnectionError("MQTT connection timed out") from error
        if self._connect_error is not None:
            error = self._connect_error
            await self.disconnect()
            raise MqttConnectionError("MQTT broker connection failed") from error

    def set_connection_lost_handler(
        self,
        handler: MqttConnectionLostHandler | None,
    ) -> None:
        """Set the unexpected-disconnect callback."""

        self._connection_lost_handler = handler

    async def subscribe(
        self,
        filters: Sequence[str],
        qos: int,
    ) -> None:
        """Subscribe to all filters and wait for SUBACK."""

        if self._client is None or self._loop is None:
            raise MqttConnectionError("MQTT client is not connected")
        if not filters:
            raise MqttConfigurationError("MQTT subscription filters are empty")
        for topic_filter in filters:
            if not topic_filter:
                raise MqttConfigurationError("MQTT subscription filter is empty")
            result, mid = self._client.subscribe(topic_filter, qos=qos)
            if result != 0:
                raise MqttProtocolError(f"MQTT subscribe returned {result}")
            future = self._loop.create_future()
            self._pending_subscriptions[mid] = future
            if mid in self._subscription_results:
                error = self._subscription_results.pop(mid)
                if error is None:
                    _set_future_result(future)
                else:
                    _set_future_exception(future, error)
            try:
                await asyncio.wait_for(
                    future,
                    timeout=self._connect_timeout,
                )
            except asyncio.TimeoutError as error:
                self._pending_subscriptions.pop(mid, None)
                raise MqttConnectionError("MQTT subscription timed out") from error
            finally:
                self._pending_subscriptions.pop(mid, None)

    async def disconnect(self) -> None:
        """Disconnect and stop the Paho network loop."""

        client, self._client = self._client, None
        for future in self._pending_subscriptions.values():
            if not future.done():
                future.cancel()
        self._pending_subscriptions.clear()
        self._subscription_results.clear()
        if client is None:
            return
        try:
            client.disconnect()
        finally:
            await asyncio.to_thread(client.loop_stop)

    def _on_connect(
        self,
        _client: Any,
        _userdata: Any,
        _flags: Any,
        reason_code: Any,
        _properties: Any,
    ) -> None:
        self._connect_error = (
            None if _reason_ok(reason_code) else RuntimeError(str(reason_code))
        )
        if self._loop is not None and self._connected is not None:
            self._loop.call_soon_threadsafe(self._connected.set)

    def _on_connect_fail(self, _client: Any, _userdata: Any) -> None:
        self._connect_error = RuntimeError("TCP connection failed")
        if self._loop is not None and self._connected is not None:
            self._loop.call_soon_threadsafe(self._connected.set)

    def _on_disconnect(
        self,
        client: Any,
        _userdata: Any,
        _disconnect_flags: Any,
        _reason_code: Any,
        _properties: Any,
    ) -> None:
        if (
            self._client is client
            and self._connection_lost_handler is not None
        ):
            self._connection_lost_handler()

    def _on_subscribe(
        self,
        _client: Any,
        _userdata: Any,
        mid: int,
        reason_codes: Any,
        _properties: Any,
    ) -> None:
        if self._loop is None:
            return
        failed = any(
            not _subscription_reason_ok(code)
            for code in _reason_codes(reason_codes)
        )
        future = self._pending_subscriptions.get(mid)
        error = (
            MqttProtocolError("MQTT broker rejected a subscription")
            if failed
            else None
        )
        if future is None:
            self._subscription_results[mid] = error
            return
        if error is None:
            self._loop.call_soon_threadsafe(_set_future_result, future)
        else:
            self._loop.call_soon_threadsafe(
                _set_future_exception,
                future,
                error,
            )


def _reason_ok(value: Any) -> bool:
    try:
        return int(value) == 0
    except (TypeError, ValueError):
        return str(value).lower() == "success"


def _subscription_reason_ok(value: Any) -> bool:
    try:
        return int(value) in {0, 1, 2}
    except (TypeError, ValueError):
        return str(value).lower() in {
            "granted qos 0",
            "granted qos 1",
            "granted qos 2",
        }


def _reason_codes(value: Any) -> tuple[Any, ...]:
    return tuple(value) if isinstance(value, (list, tuple)) else (value,)


def _set_future_result(future: asyncio.Future[None]) -> None:
    if not future.done():
        future.set_result(None)


def _set_future_exception(
    future: asyncio.Future[None],
    error: BaseException,
) -> None:
    if not future.done():
        future.set_exception(error)

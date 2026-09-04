"""Typed SmartHome discovery and realtime-session API."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote

from ..const import (
    DEVICE_DETAIL_PATH,
    DEVICE_SNAPSHOT_PATH,
    HOME_SNAPSHOT_PATH,
    CLOUD_ROUTE_SELECT_PATH,
    MESSAGE_CENTER_LOGIN_PATH,
    SMART_HOME_IOS_APP_ID,
    SMART_HOME_USER_AGENT,
)
from ..domain.models import (
    AuthSession,
    MessageChannelSession,
    RemoteDeviceDescriptor,
    RemoteDiscoverySnapshot,
    SmartHomeCloudRoute,
)
from .errors import (
    AuthExpiredError,
    InvalidResponseError,
    PermissionDeniedError,
    RateLimitedError,
    RemoteOperationError,
    TransientNetworkError,
)
from .normalizers import normalize_device_detail, normalize_snapshot
from .transport import AsyncHttpTransport, HttpResponse, UrllibHttpTransport


class SmartHomeDiscoveryApi:
    """HTTP facade for account discovery and device details."""

    def __init__(
        self,
        *,
        transport: AsyncHttpTransport | None = None,
        base_url: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._transport = transport or UrllibHttpTransport()
        self._base_url = base_url.rstrip("/") if base_url else None
        self._timeout = timeout

    async def async_get_snapshot(self, session: AuthSession) -> RemoteDiscoverySnapshot:
        """Fetch and normalize the complete homes/devices snapshot."""

        devices = await self._request(session, DEVICE_SNAPSHOT_PATH)
        homes = await self._request(session, HOME_SNAPSHOT_PATH)
        return normalize_snapshot(
            self._json(devices),
            self._json(homes),
        )

    async def async_login_message_center(
        self,
        session: AuthSession,
    ) -> MessageChannelSession:
        """Create the ephemeral message-center context for MQTT."""

        if not session.device_id or not session.pushtmid:
            raise InvalidResponseError("SmartHome client identity is unavailable")
        if len(session.pushtmid) != 64:
            raise InvalidResponseError("SmartHome message identity is invalid")
        try:
            int(session.pushtmid, 16)
        except ValueError as error:
            raise InvalidResponseError("SmartHome message identity is invalid") from error
        body = json.dumps(
            {
                "phoneos": "iOS",
                "language": "zh_CN",
                "deviceInfo": {
                    "deviceID": session.device_id,
                    "terminalType": "iphone",
                    "deviceAliasName": session.device_name,
                    "deviceType": "0",
                },
                "pushtmid": session.pushtmid,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        value = self._json(
            await self._request(
                session,
                MESSAGE_CENTER_LOGIN_PATH,
                method="POST",
                body=body,
            )
        )
        if not isinstance(value, Mapping):
            raise InvalidResponseError("message-center response is not an object")
        client_id = value.get("mqttClientId")
        mqtt_topic = value.get("mqttTopic")
        if not isinstance(client_id, str) or not client_id:
            raise InvalidResponseError("message-center response has no client id")
        if not isinstance(mqtt_topic, str) or not mqtt_topic:
            raise InvalidResponseError("message-center response has no topic")
        first_login = value.get("firstLogin")
        log_collection = value.get("logcollection")
        return MessageChannelSession(
            mqtt_client_id=client_id,
            mqtt_topic=mqtt_topic,
            first_login=first_login if isinstance(first_login, bool) else None,
            log_collection=log_collection if isinstance(log_collection, str) else None,
        )

    async def async_select_cloud_route(
        self,
        session: AuthSession,
    ) -> SmartHomeCloudRoute:
        """Resolve the dynamic SmartHome broker route."""

        body = json.dumps(
            {"version": "17.0.3.320", "huid": session.user_id},
            separators=(",", ":"),
        ).encode("utf-8")
        value = self._json(
            await self._request(
                session,
                CLOUD_ROUTE_SELECT_PATH,
                method="POST",
                body=body,
                extra_headers={
                    "huid": session.user_id,
                    "version": "17.0.3.320",
                },
            )
        )
        if not isinstance(value, Mapping):
            raise InvalidResponseError("SmartHome route response is not an object")
        host = value.get("smarthomehost")
        mqtt_port = value.get("mqtts")
        https_port = value.get("https")
        if (
            not isinstance(host, str)
            or not host
            or not isinstance(mqtt_port, int)
            or mqtt_port <= 0
            or not isinstance(https_port, int)
            or https_port <= 0
        ):
            raise InvalidResponseError("SmartHome route response is incomplete")
        expires = value.get("expires")
        role = value.get("role")
        return SmartHomeCloudRoute(
            smart_home_host=host,
            mqtt_port=mqtt_port,
            https_port=https_port,
            expires_seconds=expires if isinstance(expires, int) else None,
            role=role if isinstance(role, int) else None,
        )

    async def async_get_device_detail(
        self,
        session: AuthSession,
        dev_id: str,
    ) -> RemoteDeviceDescriptor:
        """Fetch and normalize one device detail response."""

        if not dev_id:
            raise ValueError("device id is required")
        response = await self._request(
            session,
            DEVICE_DETAIL_PATH.format(dev_id=quote(dev_id, safe="")),
        )
        return normalize_device_detail(self._json(response))

    async def async_get_device_details(
        self,
        session: AuthSession,
        devices: Sequence[str],
        *,
        max_concurrency: int = 8,
    ) -> tuple[RemoteDeviceDescriptor, ...]:
        """Fetch targeted details with bounded concurrency."""

        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        semaphore = asyncio.Semaphore(max_concurrency)

        async def fetch(dev_id: str) -> RemoteDeviceDescriptor | None:
            async with semaphore:
                try:
                    return await self.async_get_device_detail(session, dev_id)
                except AuthExpiredError:
                    raise
                except Exception:
                    return None

        results = await asyncio.gather(*(fetch(dev_id) for dev_id in devices))
        return tuple(device for device in results if device is not None)

    async def _request(
        self,
        session: AuthSession,
        path: str,
        *,
        method: str = "GET",
        body: bytes | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        if not session.hms_access_token:
            raise AuthExpiredError("HMS-lite access token is unavailable")
        origin = self._base_url or session.base_url
        headers = {
            "Accept": "*/*",
            "Accept-Language": "zh-Hans-CN;q=1",
            "Authorization": f"Bearer {session.hms_access_token}",
            "X-AppId": SMART_HOME_IOS_APP_ID,
            "X-AppVersion": "17.0.3.320",
            "X-HomeId": "(null)",
            "X-Huid": session.user_id,
            "X-Language": "zh_CN",
            "X-Model": "iPhone",
            "X-Ori-App-Name": SMART_HOME_IOS_APP_ID,
            "X-PhoneOs": "iOS",
            "X-RequestId": str(uuid.uuid4()).upper(),
            "User-Agent": SMART_HOME_USER_AGENT,
        }
        if extra_headers:
            headers.update(extra_headers)
        if body is not None:
            headers["Content-Type"] = "application/json;charset=UTF-8"
        response: HttpResponse | None = None
        for attempt in range(3):
            try:
                response = await self._transport.request(
                    method,
                    f"{origin.rstrip('/')}{path}",
                    headers,
                    body,
                    self._timeout,
                )
            except TransientNetworkError:
                if attempt == 2:
                    raise
                await asyncio.sleep(0.5 * (2**attempt))
                continue
            if response.status in {500, 502, 503, 504} and attempt < 2:
                await asyncio.sleep(0.5 * (2**attempt))
                continue
            break
        assert response is not None
        if response.status == 401:
            raise AuthExpiredError("SmartHome service session expired")
        if response.status == 403:
            raise PermissionDeniedError("SmartHome access denied")
        if response.status == 429:
            raise RateLimitedError("SmartHome service rate limited the request")
        if response.status >= 400:
            raise RemoteOperationError(f"SmartHome HTTP status {response.status}")
        return response

    @staticmethod
    def _json(response: HttpResponse) -> Any:
        try:
            value = json.loads(response.body.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InvalidResponseError("SmartHome response is not JSON") from error
        error_code = _find_error_code(value)
        if error_code in {"200201", "400000021", "400000022", "400000023", "10004"}:
            raise AuthExpiredError("SmartHome service session expired")
        return value


def _find_error_code(value: Any) -> str | None:
    """Read an error code from the response envelope only."""

    if not isinstance(value, Mapping):
        return None
    code = _direct_error_code(value)
    if code is not None:
        return code
    for key in ("error", "errorInfo", "error_info"):
        error = value.get(key)
        if isinstance(error, Mapping):
            code = _direct_error_code(error)
            if code is not None:
                return code
    return None


def _direct_error_code(value: Mapping[str, Any]) -> str | None:
    """Read an error code from one explicitly selected envelope object."""

    for key in ("error_code", "errorCode", "code"):
        candidate = value.get(key)
        if isinstance(candidate, (str, int)):
            return str(candidate)
    return None

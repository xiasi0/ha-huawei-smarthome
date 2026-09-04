"""Asynchronous HTTP transport ports."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .errors import TransientNetworkError


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Minimal HTTP response used by protocol adapters."""

    status: int
    headers: Mapping[str, str]
    body: bytes


class AsyncHttpTransport(Protocol):
    """HTTP transport port."""

    async def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None = None,
        timeout: float = 20.0,
    ) -> HttpResponse:
        """Send one HTTP request."""


class AiohttpHttpTransport:
    """Use Home Assistant's shared aiohttp client session."""

    def __init__(self, session: Any) -> None:
        self._session = session

    async def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None = None,
        timeout: float = 20.0,
    ) -> HttpResponse:
        """Send a non-blocking HTTP request."""

        try:
            import aiohttp
        except ImportError as error:  # pragma: no cover - supplied by HA
            raise TransientNetworkError("aiohttp is unavailable") from error
        try:
            async with self._session.request(
                method,
                url,
                headers=dict(headers),
                data=body,
                timeout=timeout,
            ) as response:
                return HttpResponse(
                    status=response.status,
                    headers={str(k): str(v) for k, v in response.headers.items()},
                    body=await response.read(),
                )
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as error:
            raise TransientNetworkError("SmartHome HTTP transport failed") from error


class UrllibHttpTransport:
    """Standard-library transport for standalone tests."""

    async def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None = None,
        timeout: float = 20.0,
    ) -> HttpResponse:
        """Run blocking urllib work off the event loop."""

        return await asyncio.to_thread(
            self._request_sync,
            method,
            url,
            dict(headers),
            body,
            timeout,
        )

    @staticmethod
    def _request_sync(
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                return HttpResponse(
                    status=response.status,
                    headers={str(k): str(v) for k, v in response.headers.items()},
                    body=response.read(),
                )
        except HTTPError as error:
            return HttpResponse(
                status=error.code,
                headers={str(k): str(v) for k, v in error.headers.items()},
                body=error.read(),
            )
        except (URLError, TimeoutError, OSError) as error:
            raise TransientNetworkError("SmartHome HTTP transport failed") from error

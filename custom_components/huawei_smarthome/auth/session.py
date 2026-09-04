"""Single-flight credential lifecycle for Huawei SmartHome."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Protocol

from ..domain.models import AuthSession
from ..errors import ReauthenticationRequired, TransientAuthenticationError
from .interface import AuthProvider


class CredentialStore(Protocol):
    """Credential persistence port required for refreshed sessions."""

    async def async_save(self, session: AuthSession) -> None:
        """Persist a newly issued session."""


ProviderFactory = Callable[[AuthSession], AuthProvider]
SessionListener = Callable[[AuthSession], Awaitable[None] | None]
ReauthListener = Callable[[], Awaitable[None] | None]


class SessionManager:
    """Own one account session and serialize credential refresh operations."""

    def __init__(
        self,
        session: AuthSession,
        credential_store: CredentialStore,
        provider_factory: ProviderFactory,
        *,
        refresh_margin: timedelta = timedelta(minutes=5),
        on_session_updated: SessionListener | None = None,
        on_reauthentication_required: ReauthListener | None = None,
    ) -> None:
        self._session = session
        self._credential_store = credential_store
        self._provider_factory = provider_factory
        self._refresh_margin = refresh_margin
        self._on_session_updated = on_session_updated
        self._on_reauthentication_required = on_reauthentication_required
        self._refresh_lock = asyncio.Lock()
        self._oauth_wake = asyncio.Event()
        self._hms_wake = asyncio.Event()
        self._oauth_monitor_task: asyncio.Task[None] | None = None
        self._hms_monitor_task: asyncio.Task[None] | None = None
        self._stopped = False

    @property
    def session(self) -> AuthSession:
        """Return the current session."""

        return self._session

    async def async_start(self) -> None:
        """Start the proactive monitors for both token domains."""

        if self._oauth_monitor_task is not None:
            return
        self._stopped = False
        self._oauth_monitor_task = asyncio.create_task(
            self._oauth_refresh_monitor(),
            name="huawei-smarthome-oauth-refresh",
        )
        self._hms_monitor_task = asyncio.create_task(
            self._hms_refresh_monitor(),
            name="huawei-smarthome-hms-lite-refresh",
        )

    async def async_stop(self) -> None:
        """Stop the proactive refresh monitors."""

        self._stopped = True
        self._oauth_wake.set()
        self._hms_wake.set()
        tasks = [
            task
            for task in (self._oauth_monitor_task, self._hms_monitor_task)
            if task is not None
        ]
        self._oauth_monitor_task = None
        self._hms_monitor_task = None
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def async_ensure_hms_valid(self) -> AuthSession:
        """Return a session with a valid HMS-lite token."""

        if self._session.is_hms_valid(self._refresh_margin_seconds):
            return self._session
        return await self.async_refresh_hms_lite()

    async def async_ensure_oauth_valid(self) -> AuthSession:
        """Return a session with a valid OAuth token, refreshing once if needed."""

        if self._session.is_oauth_valid(self._refresh_margin_seconds):
            return self._session
        return await self.async_refresh_oauth()

    async def async_refresh_oauth(self, *, force: bool = False) -> AuthSession:
        """Refresh OAuth once for all concurrent callers."""

        async with self._refresh_lock:
            current = self._session
            if not force and current.is_oauth_valid(self._refresh_margin_seconds):
                return current
            try:
                refreshed = await self._provider_factory(current).async_refresh_oauth(
                    current
                )
                if refreshed.generation <= current.generation:
                    refreshed = replace(
                        refreshed,
                        generation=current.generation + 1,
                    )
                await self._credential_store.async_save(refreshed)
            except ReauthenticationRequired:
                await self._notify_reauthentication_required()
                raise
            except TransientAuthenticationError:
                raise
            except Exception as error:
                await self._notify_reauthentication_required()
                raise ReauthenticationRequired(
                    "Huawei SmartHome OAuth session refresh failed"
                ) from error
            self._session = refreshed
            self._oauth_wake.set()
        await self._notify_session_updated(refreshed)
        return refreshed

    async def async_refresh_hms_lite(self, *, force: bool = False) -> AuthSession:
        """Reissue HMS-lite credentials once for all concurrent callers."""

        async with self._refresh_lock:
            current = self._session
            if not force and current.is_hms_valid(self._refresh_margin_seconds):
                return current
            try:
                refreshed = await self._provider_factory(
                    current
                ).async_refresh_hms_lite(current)
                if refreshed.generation != current.generation:
                    refreshed = replace(
                        refreshed,
                        generation=current.generation,
                    )
                await self._credential_store.async_save(refreshed)
            except ReauthenticationRequired:
                await self._notify_reauthentication_required()
                raise
            except TransientAuthenticationError:
                raise
            except Exception as error:
                await self._notify_reauthentication_required()
                raise ReauthenticationRequired(
                    "Huawei SmartHome HMS-lite token refresh failed"
                ) from error
            self._session = refreshed
            self._hms_wake.set()
        await self._notify_session_updated(refreshed)
        return refreshed

    @property
    def _refresh_margin_seconds(self) -> int:
        """Return the refresh margin as whole seconds."""

        return max(0, int(self._refresh_margin.total_seconds()))

    async def _oauth_refresh_monitor(self) -> None:
        """Refresh OAuth before expiry and stop on an unrecoverable error."""

        while not self._stopped:
            expires_at = self._session.oauth_expires_at
            if expires_at is None:
                await self._wait_for_wake(self._oauth_wake, None)
                continue
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            delay = (
                expires_at
                - datetime.now(timezone.utc)
                - self._refresh_margin
            ).total_seconds()
            if delay > 0:
                await self._wait_for_wake(self._oauth_wake, delay)
                continue
            try:
                await self.async_refresh_oauth()
            except TransientAuthenticationError:
                await self._wait_for_wake(self._oauth_wake, 30.0)
            except ReauthenticationRequired:
                return

    async def _hms_refresh_monitor(self) -> None:
        """Refresh HMS-lite credentials before expiry."""

        while not self._stopped:
            expires_at = self._session.hms_expires_at
            if expires_at is None:
                await self._wait_for_wake(self._hms_wake, None)
                continue
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            delay = (
                expires_at
                - datetime.now(timezone.utc)
                - self._refresh_margin
            ).total_seconds()
            if delay > 0:
                await self._wait_for_wake(self._hms_wake, delay)
                continue
            try:
                await self.async_ensure_oauth_valid()
                await self.async_refresh_hms_lite()
            except TransientAuthenticationError:
                await self._wait_for_wake(self._hms_wake, 30.0)
            except ReauthenticationRequired:
                return

    async def _wait_for_wake(
        self,
        wake: asyncio.Event,
        timeout: float | None,
    ) -> None:
        wake.clear()
        try:
            if timeout is None:
                await wake.wait()
            else:
                await asyncio.wait_for(wake.wait(), timeout=max(0.1, timeout))
        except asyncio.TimeoutError:
            return

    async def _notify_session_updated(self, session: AuthSession) -> None:
        if self._on_session_updated is None:
            return
        result = self._on_session_updated(session)
        if asyncio.iscoroutine(result):
            await result

    async def _notify_reauthentication_required(self) -> None:
        if self._on_reauthentication_required is None:
            return
        result = self._on_reauthentication_required()
        if asyncio.iscoroutine(result):
            await result

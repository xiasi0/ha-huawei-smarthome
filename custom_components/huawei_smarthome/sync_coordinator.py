"""Account-scoped SmartHome synchronization coordination."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
import json
import logging


_LOGGER = logging.getLogger(__name__)


class SyncKind(StrEnum):
    """Types of account synchronization supported by SmartHome."""

    FULL = "full"
    STATE = "state"


SyncHandler = Callable[[str], Awaitable[None]]


@dataclass(slots=True)
class _SyncRequest:
    """One caller waiting for a coalesced synchronization pass."""

    reason: str
    future: asyncio.Future[None]


class SmartHomeSyncCoordinator:
    """Serialize and coalesce account-level synchronization requests."""

    _TOPOLOGY_NOTIFY_TYPES = frozenset(
        {
            "deviceAdd",
            "deviceAdded",
            "deviceDelete",
            "deviceDeleted",
            "deviceInfoSync",
            "deviceMove",
            "deviceMoved",
            "deviceRemove",
            "deviceRemoved",
            "homeUpdated",
            "roomUpdated",
        }
    )

    def __init__(
        self,
        *,
        full_sync: SyncHandler,
        state_sync: SyncHandler,
    ) -> None:
        self._full_sync = full_sync
        self._state_sync = state_sync
        self._condition = asyncio.Condition()
        self._pending_full: list[_SyncRequest] = []
        self._pending_state: list[_SyncRequest] = []
        self._active_kind: SyncKind | None = None
        self._active_requests: list[_SyncRequest] = []
        self._worker: asyncio.Task[None] | None = None
        self._scheduled_full: asyncio.Task[None] | None = None
        self._scheduled_state: asyncio.Task[None] | None = None
        self._stopping = False

    async def async_request_full_sync(self, reason: str) -> None:
        """Run or join one coalesced full synchronization pass."""

        await self._submit(SyncKind.FULL, reason)

    async def async_request_state_sync(self, reason: str) -> None:
        """Run or join one coalesced state-only synchronization pass."""

        await self._submit(SyncKind.STATE, reason)

    def schedule_full_sync(
        self,
        reason: str,
        *,
        delay: float = 0.5,
    ) -> None:
        """Schedule a debounced full synchronization for an inbound event."""

        if self._stopping:
            return
        task = self._scheduled_full
        if task is not None and not task.done():
            return
        self._scheduled_full = asyncio.create_task(
            self._run_scheduled_full(reason, delay),
            name="huawei-smarthome-scheduled-full-sync",
        )

    def schedule_state_sync(self, reason: str) -> None:
        """Schedule a non-blocking state synchronization request."""

        if self._stopping:
            return
        task = self._scheduled_state
        if task is not None and not task.done():
            return
        self._scheduled_state = asyncio.create_task(
            self._run_scheduled_state(reason),
            name="huawei-smarthome-scheduled-state-sync",
        )

    async def async_stop(self) -> None:
        """Stop pending synchronization work."""

        self._stopping = True
        scheduled = self._scheduled_full
        self._scheduled_full = None
        if scheduled is not None:
            scheduled.cancel()
        scheduled_state = self._scheduled_state
        self._scheduled_state = None
        if scheduled_state is not None:
            scheduled_state.cancel()

        async with self._condition:
            pending = self._pending_full + self._pending_state
            self._pending_full.clear()
            self._pending_state.clear()
            for request in pending:
                request.future.cancel()
            self._condition.notify_all()

        worker = self._worker
        if worker is not None:
            worker.cancel()
        tasks = [
            task
            for task in (scheduled, scheduled_state, worker)
            if task is not None
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    @classmethod
    def is_topology_event(cls, payload: bytes) -> bool:
        """Return whether an MQTT payload announces topology information."""

        try:
            message = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        if not isinstance(message, Mapping):
            return False
        header = message.get("header")
        return (
            isinstance(header, Mapping)
            and header.get("notifyType") in cls._TOPOLOGY_NOTIFY_TYPES
        )

    async def _submit(self, kind: SyncKind, reason: str) -> None:
        if not reason:
            reason = kind.value
        future = asyncio.get_running_loop().create_future()
        request = _SyncRequest(reason, future)
        async with self._condition:
            if self._stopping:
                raise RuntimeError("SmartHome synchronization is stopped")
            if self._active_kind is SyncKind.FULL:
                self._active_requests.append(request)
            elif (
                self._active_kind is SyncKind.STATE
                and kind is SyncKind.STATE
            ):
                self._active_requests.append(request)
            elif kind is SyncKind.FULL:
                self._pending_full.append(request)
            else:
                self._pending_state.append(request)
            if self._worker is None or self._worker.done():
                self._worker = asyncio.create_task(
                    self._worker_loop(),
                    name="huawei-smarthome-sync-worker",
                )
            self._condition.notify()
        await future

    async def _worker_loop(self) -> None:
        while True:
            async with self._condition:
                await self._condition.wait_for(
                    lambda: (
                        self._stopping
                        or self._pending_full
                        or self._pending_state
                    )
                )
                if self._stopping:
                    pending = self._pending_full + self._pending_state
                    self._pending_full.clear()
                    self._pending_state.clear()
                    for request in pending:
                        request.future.cancel()
                    return
                if self._pending_full:
                    kind = SyncKind.FULL
                    requests = self._pending_full + self._pending_state
                    self._pending_full.clear()
                    self._pending_state.clear()
                else:
                    kind = SyncKind.STATE
                    requests = self._pending_state
                    self._pending_state = []
                self._active_kind = kind
                self._active_requests = requests

            error: BaseException | None = None
            try:
                handler = (
                    self._full_sync
                    if kind is SyncKind.FULL
                    else self._state_sync
                )
                await handler(requests[0].reason)
            except BaseException as caught:
                error = caught

            async with self._condition:
                active = self._active_requests
                self._active_requests = []
                self._active_kind = None
                for request in active:
                    if request.future.done():
                        continue
                    if error is None:
                        request.future.set_result(None)
                    else:
                        request.future.set_exception(error)
                self._condition.notify_all()

            if isinstance(error, asyncio.CancelledError):
                raise error

    async def _run_scheduled_full(self, reason: str, delay: float) -> None:
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            await self.async_request_full_sync(reason)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            _LOGGER.warning(
                "Huawei SmartHome scheduled sync failed: %s: %s",
                type(error).__name__,
                str(error),
            )
        finally:
            current = asyncio.current_task()
            if self._scheduled_full is current:
                self._scheduled_full = None

    async def _run_scheduled_state(self, reason: str) -> None:
        try:
            await self.async_request_state_sync(reason)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            _LOGGER.warning(
                "Huawei SmartHome scheduled state sync failed: %s: %s",
                type(error).__name__,
                str(error),
            )
        finally:
            current = asyncio.current_task()
            if self._scheduled_state is current:
                self._scheduled_state = None

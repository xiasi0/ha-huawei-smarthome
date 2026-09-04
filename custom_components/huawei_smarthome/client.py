"""Account client for Huawei SmartHome discovery and MQTT lifecycle."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone
import logging
import uuid
from typing import Any, Protocol

from .api.client import SmartHomeDiscoveryApi
from .api.errors import AuthExpiredError
from .auth.huawei import HuaweiSmartHomeAuthProvider
from .auth.session import SessionManager
from .const import (
    OBSERVED_MQTT_FILTER,
    OBSERVED_MQTT_PORT,
    OBSERVED_MQTT_SUBSCRIPTION_QOS,
)
from .domain.models import (
    AccountState,
    AuthSession,
    ConnectionState,
    MqttConnectionSettings,
    RemoteDeviceDescriptor,
    RemoteDiscoverySnapshot,
)
from .errors import ReauthenticationRequired
from .hwiotdevices.registry import create_hwiot_device
from .mqtt_client import HuaweiMqttClient
from .storage.credentials import CredentialBindingError
from .storage.profile_metadata import ProductMetadataStore
from .storage.state import AccountStateStore


_LOGGER = logging.getLogger(__name__)


class CredentialStore(Protocol):
    """Account credential and local device-preference storage."""

    async def async_load(
        self,
        account: str,
        *,
        identity_fingerprint: str | None = None,
    ) -> AuthSession | None:
        """Load credentials bound to the account and client identity."""

    async def async_save(self, session: AuthSession) -> None:
        """Persist a refreshed account session."""

    async def async_get_device_exclusions(self, account: str) -> frozenset[str]:
        """Load devices excluded from the local HA projection."""


class HuaweiSmartHomeClient:
    """Own one account, its discovered devices and its MQTT lifecycle."""

    def __init__(
        self,
        *,
        account: str,
        identity_fingerprint: str,
        selected_home_ids: frozenset[str] | None,
        credential_store: CredentialStore,
        state_store: AccountStateStore,
        api: SmartHomeDiscoveryApi,
        metadata_store: ProductMetadataStore | None = None,
        mqtt: HuaweiMqttClient | None = None,
        mqtt_enabled: bool = True,
        reconnect_min: float = 5.0,
        reconnect_max: float = 300.0,
    ) -> None:
        if not account:
            raise ValueError("account is required")
        if reconnect_min <= 0 or reconnect_max < reconnect_min:
            raise ValueError("MQTT reconnect backoff is invalid")
        self.account = account
        self.identity_fingerprint = identity_fingerprint
        self.credentials = credential_store
        self.state_store = state_store
        self.api = api
        self.metadata_store = metadata_store
        self.selected_home_ids = selected_home_ids or None
        self.mqtt_enabled = mqtt_enabled
        self.mqtt = mqtt or HuaweiMqttClient(
            on_state_changed=self._mqtt_state_changed,
        )
        self.mqtt.set_message_handler(self._mqtt_message_received)
        self.state = AccountState(
            selected_home_ids=selected_home_ids or frozenset(),
        )
        self.session: AuthSession | None = None
        self.session_manager: SessionManager | None = None
        self._excluded_device_ids: frozenset[str] = frozenset()
        self._refresh_lock = asyncio.Lock()
        self._reconnect_task: asyncio.Task[None] | None = None
        self._operation_lock = asyncio.Lock()
        self._hwiot_devices: dict[tuple[str, str], Any] = {}
        self._reconnect_min = reconnect_min
        self._reconnect_max = reconnect_max
        self._started = False

    @property
    def devices(self) -> Mapping[tuple[str, str], RemoteDeviceDescriptor]:
        """Return the current discovered devices."""

        return self.state.devices

    @property
    def homes(self):
        """Return the current discovered remote homes."""

        return self.state.homes

    @property
    def excluded_device_ids(self) -> frozenset[str]:
        """Return devices excluded from the local HA projection."""

        return self._excluded_device_ids

    @property
    def hwiot_devices(self) -> Mapping[tuple[str, str], Any]:
        """Return instantiated product devices."""

        return self._hwiot_devices

    async def async_start(self) -> None:
        """Restore the account, discover devices and start MQTT."""

        if self._started:
            return
        self._started = True
        stored = await self.state_store.async_load()
        if stored is not None:
            self.state = stored
        self.state.selected_home_ids = self.selected_home_ids or frozenset()
        self.state.connection = ConnectionState.AUTHENTICATING
        try:
            session = await self.credentials.async_load(
                self.account,
                identity_fingerprint=self.identity_fingerprint or None,
            )
            if session is None:
                raise ReauthenticationRequired(
                    "Huawei SmartHome credentials are missing"
                )
            self._excluded_device_ids = (
                await self.credentials.async_get_device_exclusions(self.account)
            )
            self.session_manager = self._new_session_manager(session)
            await self.session_manager.async_start()
            if self.mqtt_enabled:
                session = await self.session_manager.async_ensure_oauth_valid()
            session = await self.session_manager.async_ensure_hms_valid()
            self.session = session
            await self._discover_with_token_recovery(session)
            if self.mqtt_enabled:
                try:
                    await self._connect_mqtt(session)
                except ReauthenticationRequired:
                    raise
                except Exception as error:
                    _LOGGER.warning(
                        "Huawei SmartHome MQTT startup failed: %s: %s",
                        type(error).__name__,
                        str(error),
                    )
                    self.state.connection = ConnectionState.DEGRADED
                self._reconnect_task = asyncio.create_task(
                    self._reconnect_loop(),
                    name="huawei-smarthome-mqtt-reconnect",
                )
        except (ReauthenticationRequired, CredentialBindingError):
            self.state.connection = ConnectionState.REAUTH_REQUIRED
            self.state.last_error = "Huawei SmartHome authentication required"
            raise ReauthenticationRequired(
                "Huawei SmartHome authentication required"
            )
        except Exception:
            self.state.connection = ConnectionState.ERROR
            self.state.last_error = "Huawei SmartHome discovery failed"
            raise

    async def async_request_refresh(self) -> AccountState:
        """Refresh the account device snapshot."""

        async with self._refresh_lock:
            try:
                session = await self._ensure_hms_session()
                await self._discover_with_token_recovery(session)
            except (
                ReauthenticationRequired,
                CredentialBindingError,
            ) as error:
                self.state.connection = ConnectionState.REAUTH_REQUIRED
                self.state.last_error = "Huawei SmartHome authentication required"
                raise ReauthenticationRequired(
                    "Huawei SmartHome authentication required"
                ) from error
            except Exception:
                self.state.connection = ConnectionState.ERROR
                self.state.last_error = "Huawei SmartHome discovery failed"
                raise
        return self.state

    async def async_stop(self) -> None:
        """Stop MQTT and the account session."""

        self._started = False
        task, self._reconnect_task = self._reconnect_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for device in self._hwiot_devices.values():
            device.close()
        self._hwiot_devices.clear()
        await self.mqtt.async_stop()
        if self.session_manager is not None:
            await self.session_manager.async_stop()
            self.session_manager = None
        self.state.connection = ConnectionState.STOPPED
        await self.state_store.async_save(self.state)

    async def _discover(self, session: AuthSession) -> None:
        self.state.connection = ConnectionState.DISCOVERING
        snapshot = await self.api.async_get_snapshot(session)
        snapshot = self._scope_snapshot(snapshot)
        snapshot = await self._hydrate_device_details(session, snapshot)
        snapshot = await self._enrich_product_metadata(snapshot)
        if not snapshot.complete:
            raise RuntimeError("Huawei SmartHome snapshot is incomplete")
        devices = {device.key: device for device in snapshot.devices}
        if len(devices) != len(snapshot.devices):
            raise RuntimeError("Huawei SmartHome snapshot contains duplicate devices")
        self.state.homes = {home.home_id: home for home in snapshot.homes}
        self.state.devices = devices
        self._sync_hwiot_devices()
        self.state.device_home_index = _device_home_index(snapshot)
        self.state.revision += 1
        self.state.last_snapshot_at = snapshot.received_at
        self.state.last_success_at = snapshot.received_at
        self.state.stale_since = None
        self.state.last_error = None
        self.state.connection = (
            ConnectionState.RUNNING
            if self.mqtt.state is ConnectionState.RUNNING
            else ConnectionState.READY
        )
        await self.state_store.async_save(self.state)

    def _scope_snapshot(
        self,
        snapshot: RemoteDiscoverySnapshot,
    ) -> RemoteDiscoverySnapshot:
        """Apply the configured local home scope."""

        if self.selected_home_ids is None:
            return snapshot
        selected = self.selected_home_ids
        return replace(
            snapshot,
            homes=tuple(
                home
                for home in snapshot.homes
                if home.home_id in selected
            ),
            devices=tuple(
                device
                for device in snapshot.devices
                if device.home_id in selected
            ),
            device_home_index={
                dev_id: frozenset(
                    home_id
                    for home_id in home_ids
                    if home_id in selected
                )
                for dev_id, home_ids in snapshot.device_home_index.items()
                if any(home_id in selected for home_id in home_ids)
            },
        )

    async def _hydrate_device_details(
        self,
        session: AuthSession,
        snapshot: RemoteDiscoverySnapshot,
    ) -> RemoteDiscoverySnapshot:
        """Merge the verified per-device detail response."""

        device_ids = tuple(
            device.dev_id
            for device in snapshot.devices
            if (device.node_type or "").strip().upper() != "GROUP"
        )
        if not device_ids:
            return snapshot
        details = await self.api.async_get_device_details(session, device_ids)
        details_by_id = {detail.dev_id: detail for detail in details}
        return replace(
            snapshot,
            devices=tuple(
                _merge_device_detail(device, details_by_id.get(device.dev_id))
                for device in snapshot.devices
            ),
        )

    async def _enrich_product_metadata(
        self,
        snapshot: RemoteDiscoverySnapshot,
    ) -> RemoteDiscoverySnapshot:
        """Apply cached Product Profile metadata without network I/O."""

        if self.metadata_store is None:
            return snapshot
        names = await self.metadata_store.async_get_manufacturer_names(
            device.prod_id
            for device in snapshot.devices
            if (device.node_type or "").strip().upper() != "GROUP"
        )
        if not names:
            return snapshot
        return replace(
            snapshot,
            devices=tuple(
                replace(
                    device,
                    manufacturer=(
                        names.get(device.prod_id.strip())
                        if isinstance(device.prod_id, str)
                        and device.prod_id.strip()
                        else None
                    )
                    or device.manufacturer,
                )
                for device in snapshot.devices
            ),
        )

    async def _discover_with_token_recovery(
        self,
        session: AuthSession,
    ) -> None:
        """Retry discovery once after an HMS-lite token rejection."""

        try:
            await self._discover(session)
        except AuthExpiredError:
            if self.session_manager is None:
                raise
            session = await self.session_manager.async_refresh_hms_lite(force=True)
            self.session = session
            await self._discover(session)

    async def _ensure_hms_session(self) -> AuthSession:
        if self.session_manager is None:
            session = await self.credentials.async_load(
                self.account,
                identity_fingerprint=self.identity_fingerprint or None,
            )
            if session is None:
                raise ReauthenticationRequired(
                    "Huawei SmartHome credentials are missing"
                )
            self._excluded_device_ids = (
                await self.credentials.async_get_device_exclusions(self.account)
            )
            self.session_manager = self._new_session_manager(session)
            await self.session_manager.async_start()
        session = await self.session_manager.async_ensure_hms_valid()
        self.session = session
        return session

    def _new_session_manager(self, session: AuthSession) -> SessionManager:
        return SessionManager(
            session,
            self.credentials,
            self._provider_for_session,
            on_session_updated=self._session_updated,
            on_reauthentication_required=self._reauthentication_required,
        )

    def _provider_for_session(
        self,
        session: AuthSession,
    ) -> HuaweiSmartHomeAuthProvider:
        return HuaweiSmartHomeAuthProvider(
            device_id=session.device_id,
            device_name=session.device_name,
            pushtmid=session.pushtmid,
            identity_fingerprint=session.identity_fingerprint,
        )

    async def _session_updated(self, session: AuthSession) -> None:
        previous = self.session
        self.session = session
        if (
            self._started
            and self.mqtt_enabled
            and previous is not None
            and previous.oauth_access_token != session.oauth_access_token
        ):
            try:
                await self._connect_mqtt(session)
            except ReauthenticationRequired:
                raise
            except Exception as error:
                _LOGGER.warning(
                    "Huawei SmartHome MQTT token rotation failed: %s: %s",
                    type(error).__name__,
                    str(error),
                )
                self.state.connection = ConnectionState.DEGRADED

    async def _reauthentication_required(self) -> None:
        self.state.connection = ConnectionState.REAUTH_REQUIRED
        self.state.last_error = "Huawei SmartHome authentication required"

    async def _connect_mqtt(self, session: AuthSession) -> None:
        """Create a fresh message-center context and MQTT generation."""

        async with self._operation_lock:
            await self.api.async_login_message_center(session)
            route = await self.api.async_select_cloud_route(session)
            settings = MqttConnectionSettings(
                broker_host=route.smart_home_host,
                broker_port=OBSERVED_MQTT_PORT,
                client_id=str(uuid.uuid4()).upper(),
                subscription_filters=(OBSERVED_MQTT_FILTER,),
                subscription_qos=OBSERVED_MQTT_SUBSCRIPTION_QOS,
                username=session.user_id,
                password=session.oauth_access_token,
                control_source=session.device_name,
                use_tls=True,
                keepalive=60,
                clean_session=True,
            )
            await self.mqtt.async_start(settings)

    async def _reconnect_loop(self) -> None:
        """Recover the MQTT connection after a disconnect."""

        delay = self._reconnect_min
        while self._started:
            if self.mqtt.state is ConnectionState.RUNNING:
                await self.mqtt.async_wait_connection_lost()
            else:
                await asyncio.sleep(delay)
            if not self._started:
                return
            self.state.connection = ConnectionState.RECONNECT_BACKOFF
            try:
                if self.session_manager is None:
                    raise ReauthenticationRequired(
                        "Huawei SmartHome session manager is stopped"
                    )
                session = await self.session_manager.async_ensure_oauth_valid()
                session = await self.session_manager.async_ensure_hms_valid()
                await self._connect_mqtt(session)
                delay = self._reconnect_min
            except ReauthenticationRequired:
                self.state.connection = ConnectionState.REAUTH_REQUIRED
                return
            except asyncio.CancelledError:
                raise
            except Exception as error:
                _LOGGER.warning(
                    "Huawei SmartHome MQTT reconnect failed: %s: %s",
                    type(error).__name__,
                    str(error),
                )
                self.state.connection = ConnectionState.DEGRADED
                delay = min(delay * 2, self._reconnect_max)

    async def _mqtt_state_changed(self, state: ConnectionState) -> None:
        """Reflect MQTT lifecycle state in the account state."""

        self.state.connection = state
        if state is ConnectionState.RUNNING:
            self.state.last_error = None
        elif state is ConnectionState.DEGRADED:
            self.state.last_error = "Huawei SmartHome MQTT is unavailable"

    def _mqtt_message_received(self, topic: str, payload: bytes) -> None:
        """Route one MQTT payload to the matching product devices."""

        self.state.last_event_at = datetime.now(timezone.utc)
        for device in tuple(self._hwiot_devices.values()):
            device.handle_mqtt_message(topic, payload)

    def _sync_hwiot_devices(self) -> None:
        """Keep product device objects aligned with the latest snapshot."""

        current: dict[tuple[str, str], Any] = {}
        for descriptor in self.state.devices.values():
            if (descriptor.node_type or "").strip().upper() == "GROUP":
                continue
            existing = self._hwiot_devices.get(descriptor.key)
            if (
                existing is not None
                and str(existing.prod_id).strip().lower()
                == str(descriptor.prod_id or "").strip().lower()
            ):
                existing.update_descriptor(descriptor)
                current[descriptor.key] = existing
                continue
            if existing is not None:
                existing.close()
            device = create_hwiot_device(descriptor, self.mqtt)
            if device is not None:
                current[descriptor.key] = device
        for key, device in self._hwiot_devices.items():
            if key not in current:
                device.close()
        self._hwiot_devices = current


def _device_home_index(
    snapshot: RemoteDiscoverySnapshot,
) -> dict[str, frozenset[str]]:
    """Build the device-to-home index used by the account state."""

    if snapshot.device_home_index:
        return {
            str(dev_id): frozenset(home_ids)
            for dev_id, home_ids in snapshot.device_home_index.items()
            if home_ids
        }
    derived: dict[str, set[str]] = {}
    for device in snapshot.devices:
        derived.setdefault(device.dev_id, set()).add(device.home_id)
    return {
        dev_id: frozenset(home_ids)
        for dev_id, home_ids in derived.items()
    }


def _merge_device_detail(
    device: RemoteDeviceDescriptor,
    detail: RemoteDeviceDescriptor | None,
) -> RemoteDeviceDescriptor:
    """Keep list identity while adding detail metadata."""

    if detail is None:
        return device
    return replace(
        device,
        gateway_id=detail.gateway_id or device.gateway_id,
        prod_id=detail.prod_id or device.prod_id,
        device_type_id=detail.device_type_id or device.device_type_id,
        model=detail.model or device.model,
        manufacturer=detail.manufacturer or device.manufacturer,
        manufacturer_code=detail.manufacturer_code or device.manufacturer_code,
        firmware_version=detail.firmware_version or device.firmware_version,
        protocol_type=detail.protocol_type or device.protocol_type,
        service_states=detail.service_states or device.service_states,
        online=detail.online if detail.online is not None else device.online,
    )

"""Persistent credentials with two independent token domains."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from ..const import ACCOUNT_STORAGE_PREFIX, CREDENTIAL_STORAGE_KEY
from ..domain.models import AuthSession
from .identity import account_identity_key
from .locking import storage_lock


CREDENTIAL_STORAGE_VERSION = 1


def account_storage_key(account: str) -> str:
    """Return the phone-named account credential file key."""

    account = account.strip()
    if not account:
        raise ValueError("account is required")
    if account in {".", ".."} or any(
        char in '<>:"/\\|?*' or ord(char) < 32
        for char in account
    ):
        raise ValueError("account cannot be used as a storage filename")
    return f"{ACCOUNT_STORAGE_PREFIX}/{account}.json"


class CredentialBindingError(ValueError):
    """Stored credentials do not belong to the requested identity."""


class HomeAssistantCredentialStore:
    """Store one account credential record in one phone-named JSON file."""

    def __init__(self, hass: Any | None = None, *, store: Any | None = None) -> None:
        if store is not None:
            self._store = store
            self._stores: dict[str, Any] = {}
            self._legacy_store = None
            self._migration_done = True
            return
        from homeassistant.helpers.storage import Store

        self._store = None
        self._hass = hass
        self._stores = {}
        self._legacy_store = Store(
            hass,
            CREDENTIAL_STORAGE_VERSION,
            CREDENTIAL_STORAGE_KEY,
        )
        self._migration_done = False

    def _store_for_account(self, account: str) -> Any:
        """Return the Store whose filename is bound to one account."""

        if self._store is not None:
            return self._store
        key = account_storage_key(account)
        store = self._stores.get(key)
        if store is None:
            from homeassistant.helpers.storage import Store

            store = Store(self._hass, CREDENTIAL_STORAGE_VERSION, key)
            self._stores[key] = store
        return store

    async def async_load(
        self,
        account: str,
        *,
        identity_fingerprint: str | None = None,
    ) -> AuthSession | None:
        """Load credentials only when account and identity bindings match."""

        account = account.strip()
        key = account_storage_key(account)
        await self._ensure_legacy_migrated()
        async with storage_lock(key):
            raw = await self._store_for_account(account).async_load()
            if not isinstance(raw, Mapping):
                return None
            stored_account = raw.get("account")
            if (
                not isinstance(stored_account, str)
                or account_identity_key(stored_account)
                != account_identity_key(account)
            ):
                raise CredentialBindingError(
                    "credential account binding is inconsistent"
                )
            stored_fingerprint = raw.get("identity_fingerprint")
            if identity_fingerprint and stored_fingerprint != identity_fingerprint:
                raise CredentialBindingError(
                    "credential identity binding does not match"
                )
            return auth_session_from_storage(raw)

    async def async_save(self, session: AuthSession) -> None:
        """Persist one fully validated account session."""

        key = account_storage_key(session.account)
        await self._ensure_legacy_migrated()
        async with storage_lock(key):
            current = await self._store_for_account(session.account).async_load()
            await self._store_for_account(session.account).async_save(
                _credential_storage_record(
                    session,
                    excluded_device_ids=_device_exclusions_from_storage(current),
                )
            )

    async def async_get_device_exclusions(self, account: str) -> frozenset[str]:
        """Return device identifiers the user removed from this account."""

        account = account.strip()
        key = account_storage_key(account)
        await self._ensure_legacy_migrated()
        async with storage_lock(key):
            raw = await self._store_for_account(account).async_load()
            return frozenset(_device_exclusions_from_storage(raw))

    async def async_add_device_exclusion(
        self,
        account: str,
        device_identifier: str,
    ) -> None:
        """Persist one local HA device exclusion for the account."""

        account = account.strip()
        device_identifier = device_identifier.strip()
        if not device_identifier:
            raise ValueError("device identifier is required")
        key = account_storage_key(account)
        await self._ensure_legacy_migrated()
        async with storage_lock(key):
            store = self._store_for_account(account)
            raw = await store.async_load()
            if not isinstance(raw, Mapping) or not auth_session_from_storage(raw):
                raise CredentialBindingError(
                    "account credentials are missing"
                )
            exclusions = _device_exclusions_from_storage(raw)
            exclusions.add(device_identifier)
            next_record = dict(raw)
            next_record["storage_schema_version"] = CREDENTIAL_STORAGE_VERSION
            next_record["excluded_device_ids"] = sorted(exclusions)
            await store.async_save(next_record)

    async def async_remove(self, account: str) -> None:
        """Remove credentials for one account."""

        key = account_storage_key(account)
        await self._ensure_legacy_migrated()
        async with storage_lock(key):
            store = self._store_for_account(account)
            remove = getattr(store, "async_remove", None)
            if callable(remove):
                await remove()
            else:
                await store.async_save(None)

    async def _ensure_legacy_migrated(self) -> None:
        """Split the old aggregate credential file once, when present."""

        if self._migration_done or self._legacy_store is None:
            return
        async with storage_lock(CREDENTIAL_STORAGE_KEY):
            if self._migration_done:
                return
            raw = await self._legacy_store.async_load()
            accounts = raw.get("accounts") if isinstance(raw, Mapping) else None
            if not isinstance(accounts, Mapping):
                self._migration_done = True
                return
            records: dict[str, AuthSession] = {}
            invalid_record = False
            for value in accounts.values():
                if not isinstance(value, Mapping):
                    invalid_record = True
                    continue
                session = auth_session_from_storage(value)
                if session is None:
                    invalid_record = True
                    continue
                try:
                    account_key = account_storage_key(session.account)
                except ValueError:
                    invalid_record = True
                    continue
                records.setdefault(account_key, session)
            for account_key, session in records.items():
                async with storage_lock(account_key):
                    store = self._store_for_account(session.account)
                    if await store.async_load() is None:
                        await store.async_save(_credential_storage_record(session))
            if not invalid_record:
                remove = getattr(self._legacy_store, "async_remove", None)
                if callable(remove):
                    await remove()
            self._migration_done = True


def _credential_storage_record(
    session: AuthSession,
    *,
    excluded_device_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Add the per-file schema marker to one credential record."""

    return {
        "storage_schema_version": CREDENTIAL_STORAGE_VERSION,
        "excluded_device_ids": sorted(excluded_device_ids or ()),
        **auth_session_to_storage(session),
    }


def _device_exclusions_from_storage(value: Any) -> set[str]:
    """Read validated local device exclusions from one account record."""

    if not isinstance(value, Mapping):
        return set()
    raw = value.get("excluded_device_ids", ())
    if not isinstance(raw, (list, tuple, set)):
        return set()
    return {
        item.strip()
        for item in raw
        if isinstance(item, str) and item.strip()
    }


def auth_session_to_storage(session: AuthSession) -> dict[str, Any]:
    """Serialize credentials without losing token-domain boundaries."""

    return {
        "account": session.account,
        "user_id": session.user_id,
        "service_token": session.service_token,
        "hms_access_token": session.hms_access_token,
        "hms_refresh_token": session.hms_refresh_token,
        "hms_expires_at": _datetime_to_storage(session.hms_expires_at),
        "oauth_access_token": session.oauth_access_token,
        "oauth_expires_at": _datetime_to_storage(session.oauth_expires_at),
        "device_id": session.device_id,
        "device_name": session.device_name,
        "pushtmid": session.pushtmid,
        "identity_fingerprint": session.identity_fingerprint,
        "app_id": session.app_id,
        "base_url": session.base_url,
        "home_zone": session.home_zone,
        "oauth_domain": session.oauth_domain,
        "site_domain": session.site_domain,
        "generation": session.generation,
    }


def auth_session_from_storage(value: Any) -> AuthSession | None:
    """Deserialize a complete credential record or return ``None``."""

    if not isinstance(value, Mapping):
        return None
    required = (
        value.get("account"),
        value.get("user_id"),
        value.get("service_token"),
    )
    if not all(isinstance(item, str) and item for item in required):
        return None
    return AuthSession(
        account=str(value["account"]),
        user_id=str(value["user_id"]),
        service_token=str(value["service_token"]),
        hms_access_token=_optional_text(value.get("hms_access_token")),
        hms_refresh_token=_optional_text(value.get("hms_refresh_token")),
        hms_expires_at=_datetime_from_storage(value.get("hms_expires_at")),
        oauth_access_token=_optional_text(value.get("oauth_access_token")),
        oauth_expires_at=_datetime_from_storage(value.get("oauth_expires_at")),
        device_id=str(value.get("device_id") or ""),
        device_name=str(value.get("device_name") or "huawei-smarthome"),
        pushtmid=_optional_text(value.get("pushtmid")),
        identity_fingerprint=_optional_text(value.get("identity_fingerprint")),
        app_id=str(value.get("app_id") or "com.huawei.smarthome-ios"),
        base_url=str(value.get("base_url") or "https://smarthome.hicloud.com"),
        home_zone=_optional_text(value.get("home_zone")),
        oauth_domain=_optional_text(value.get("oauth_domain")),
        site_domain=_optional_text(value.get("site_domain")),
        generation=(value.get("generation") if isinstance(value.get("generation"), int) else 0),
    )


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _datetime_to_storage(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _datetime_from_storage(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

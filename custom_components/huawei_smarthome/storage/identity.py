"""Persistent account-bound client identity for Huawei risk control."""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

from ..const import IDENTITY_STORAGE_KEY
from .locking import storage_lock


IDENTITY_STORAGE_VERSION = 1
DEFAULT_DEVICE_NAME = "huawei-smarthome"


class JsonStore(Protocol):
    """Small store port used by the identity implementation and tests."""

    async def async_load(self) -> Any:
        """Load one JSON-compatible value."""

    async def async_save(self, value: Any) -> None:
        """Save one JSON-compatible value."""


def account_identity_key(account: str) -> str:
    """Return a stable non-reversible lookup key for an account."""

    return hashlib.sha256(account.strip().casefold().encode("utf-8")).hexdigest()


def identity_fingerprint(identity: Mapping[str, Any]) -> str:
    """Fingerprint the stable identity fields, excluding the account name."""

    value = {
        "device_id": identity.get("device_id"),
        "device_name": identity.get("device_name"),
        "pushtmid": identity.get("pushtmid"),
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class ClientIdentityStore:
    """Persist one stable client identity per Huawei account."""

    def __init__(self, hass: Any | None = None, *, store: JsonStore | None = None) -> None:
        if store is not None:
            self._store = store
            return
        from homeassistant.helpers.storage import Store

        self._store = Store(hass, IDENTITY_STORAGE_VERSION, IDENTITY_STORAGE_KEY)

    @property
    def _lock(self):
        """Return the process-wide lock for the identity Store."""

        return storage_lock(IDENTITY_STORAGE_KEY)

    async def async_get_or_create(self, account: str) -> dict[str, Any]:
        """Reuse an existing account identity or create it once."""

        account = account.strip()
        if not account:
            raise ValueError("account is required")
        key = account_identity_key(account)
        async with self._lock:
            raw = await self._store.async_load()
            if raw is None:
                accounts: Mapping[str, Any] = {}
            elif isinstance(raw, Mapping) and isinstance(raw.get("accounts"), Mapping):
                accounts = raw["accounts"]
            else:
                raise ValueError("Huawei SmartHome identity storage is invalid")
            stored = accounts.get(key)
            if stored is not None:
                if not isinstance(stored, Mapping):
                    raise ValueError("Huawei SmartHome identity record is invalid")
                stored_account = stored.get("account")
                if not isinstance(stored_account, str) or not stored_account:
                    raise ValueError("identity account binding is missing")
                if account_identity_key(stored_account) != key:
                    raise ValueError("identity account binding is inconsistent")
                account = stored_account
                stored_fingerprint = stored.get("identity_fingerprint")
                if (
                    stored_fingerprint is not None
                    and stored_fingerprint != identity_fingerprint(stored)
                ):
                    raise ValueError("stored Huawei SmartHome identity fingerprint is invalid")
                device_id = stored.get("device_id")
                if not isinstance(device_id, str) or not device_id:
                    raise ValueError(
                        "stored Huawei SmartHome client identity is invalid; "
                        "remove it manually to create a new identity"
                    )
                device_name = stored.get("device_name")
                device_name = (
                    device_name
                    if isinstance(device_name, str) and device_name
                    else DEFAULT_DEVICE_NAME
                )
                pushtmid = stored.get("pushtmid")
                if not _valid_pushtmid(pushtmid):
                    raise ValueError(
                        "stored Huawei SmartHome client identity is invalid; "
                        "remove it manually to create a new identity"
                    )
                identity = dict(stored)
                identity.update(
                    {
                        "account": account,
                        "device_id": device_id,
                        "device_name": device_name,
                        "pushtmid": pushtmid,
                        "identity_version": IDENTITY_STORAGE_VERSION,
                        "created_at": _existing_or_now(stored.get("created_at")),
                        "last_used_at": _now(),
                        "device_info": _device_info(device_id, device_name),
                        "message_center_device_info": (
                            _message_center_device_info(device_id, device_name)
                        ),
                    }
                )
                identity["identity_fingerprint"] = identity_fingerprint(identity)
                accounts_next = dict(accounts)
                accounts_next[key] = identity
                await self._store.async_save({"accounts": accounts_next})
                return identity

            identity = _new_identity(account)
            accounts_next = dict(accounts) if isinstance(accounts, Mapping) else {}
            accounts_next[key] = identity
            await self._store.async_save({"accounts": accounts_next})
            return identity


def _new_identity(account: str) -> dict[str, Any]:
    """Create one stable identity record."""

    device_id = str(uuid.uuid4()).upper()
    device_name = DEFAULT_DEVICE_NAME
    identity: dict[str, Any] = {
        "account": account,
        "identity_version": IDENTITY_STORAGE_VERSION,
        "device_id": device_id,
        "device_name": device_name,
        "pushtmid": secrets.token_hex(32),
        "created_at": _now(),
        "last_used_at": _now(),
        "device_info": _device_info(device_id, device_name),
        "message_center_device_info": _message_center_device_info(
            device_id, device_name
        ),
    }
    identity["identity_fingerprint"] = identity_fingerprint(identity)
    return identity


def _now() -> str:
    """Return an ISO-8601 UTC timestamp for identity metadata."""

    return datetime.now(timezone.utc).isoformat()


def _existing_or_now(value: Any) -> str:
    """Keep a valid creation timestamp when one is already stored."""

    return value if isinstance(value, str) and value else _now()


def _valid_pushtmid(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _device_info(device_id: str, device_name: str) -> dict[str, Any]:
    return {
        "terminalCategory": 9,
        "deviceType": 6,
        "deviceID": device_id,
        "terminalType": "iPhone",
        "deviceAliasName": device_name,
        "uuid": device_id,
    }


def _message_center_device_info(
    device_id: str,
    device_name: str,
) -> dict[str, Any]:
    return {
        "deviceID": device_id,
        "terminalType": "iphone",
        "deviceAliasName": device_name,
        "deviceType": "0",
    }

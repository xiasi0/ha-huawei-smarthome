"""Configuration flow for Huawei SmartHome."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .api.client import SmartHomeDiscoveryApi
from .api.errors import SmartHomeApiError
from .api.transport import AiohttpHttpTransport
from .auth.huawei import HuaweiSmartHomeAuthProvider
from .auth.interface import LoginChallenge
from .const import (
    CONF_ACCOUNT,
    CONF_IDENTITY_FINGERPRINT,
    CONF_PASSWORD,
    CONF_SELECTED_HOME_IDS,
    CONF_USER_ID,
    DOMAIN,
)
from .domain.models import AuthSession, RemoteDiscoverySnapshot
from .errors import (
    AuthenticationError,
    InvalidCredentialsError,
    InvalidProtocolDataError,
)
from .storage.credentials import HomeAssistantCredentialStore
from .storage.identity import ClientIdentityStore


_LOGGER = logging.getLogger(__name__)


class HuaweiSmartHomeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up one Huawei SmartHome account."""

    VERSION = 1

    def __init__(self) -> None:
        self._account = ""
        self._identity: Mapping[str, Any] | None = None
        self._provider: HuaweiSmartHomeAuthProvider | None = None
        self._challenge: LoginChallenge | None = None
        self._session: AuthSession | None = None
        self._snapshot: RemoteDiscoverySnapshot | None = None
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Collect credentials and run the complete initial auth chain."""

        errors: dict[str, str] = {}
        if user_input is not None:
            account = str(user_input.get(CONF_ACCOUNT, "")).strip()
            password = str(user_input.get(CONF_PASSWORD, ""))
            if not account or not password:
                errors["base"] = "invalid_auth"
            else:
                self._account = account
                try:
                    identity = await ClientIdentityStore(self.hass).async_get_or_create(
                        account
                    )
                    self._identity = identity
                    self._provider = HuaweiSmartHomeAuthProvider(
                        device_id=str(identity["device_id"]),
                        device_name=str(identity["device_name"]),
                        pushtmid=str(identity["pushtmid"]),
                        identity_fingerprint=str(identity["identity_fingerprint"]),
                    )
                    result = await self._provider.async_begin_login(account, password)
                except InvalidCredentialsError:
                    errors["base"] = "invalid_auth"
                except ValueError as error:
                    _LOGGER.warning(
                        "Huawei SmartHome client identity is unusable: %s",
                        type(error).__name__,
                    )
                    errors["base"] = "cannot_connect"
                except AuthenticationError as error:
                    _LOGGER.warning(
                        "Huawei SmartHome account login failed: %s",
                        type(error).__name__,
                    )
                    errors["base"] = "cannot_connect"
                else:
                    if result.challenge is not None:
                        self._challenge = result.challenge
                        return await self.async_step_challenge()
                    if result.session is not None:
                        self._session = result.session
                        return await self._prepare_discovery()
                    errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ACCOUNT): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_challenge(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Collect an optional device challenge code when required."""

        if user_input is not None:
            code = str(user_input.get("challenge_code", "")).strip()
            if not self._provider or not code:
                return self.async_show_form(
                    step_id="challenge",
                    data_schema=vol.Schema({vol.Required("challenge_code"): str}),
                    errors={"base": "invalid_auth"},
                )
            try:
                self._session = await self._provider.async_complete_challenge(code)
            except InvalidCredentialsError:
                return self.async_show_form(
                    step_id="challenge",
                    data_schema=vol.Schema({vol.Required("challenge_code"): str}),
                    errors={"base": "invalid_auth"},
                )
            except AuthenticationError as error:
                _LOGGER.warning(
                    "Huawei SmartHome challenge failed: %s",
                    type(error).__name__,
                )
                return self.async_abort(reason="cannot_connect")
            return await self._prepare_discovery()

        description_placeholders = {}
        if self._challenge is not None:
            description_placeholders = {"prompt": self._challenge.prompt}
        return self.async_show_form(
            step_id="challenge",
            data_schema=vol.Schema({vol.Required("challenge_code"): str}),
            description_placeholders=description_placeholders,
        )

    async def async_step_home(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Select remote homes without creating HA areas."""

        if self._snapshot is None:
            return self.async_abort(reason="cannot_connect")
        options = {home.home_id: home.name for home in self._snapshot.homes}
        if user_input is not None:
            selected = tuple(
                str(value)
                for value in user_input.get(CONF_SELECTED_HOME_IDS, ())
                if str(value) in options
            )
            if options and not selected:
                return self.async_show_form(
                    step_id="home",
                    data_schema=_home_schema(options),
                    errors={"base": "home_required"},
                )
            return await self._async_create_entry(selected)
        return self.async_show_form(
            step_id="home",
            data_schema=_home_schema(options),
        )

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any],
    ) -> ConfigFlowResult:
        """Reauthenticate an existing SmartHome account."""

        entry_id = self.context.get("entry_id")
        self._reauth_entry = (
            self.hass.config_entries.async_get_entry(entry_id)
            if entry_id
            else None
        )
        if self._reauth_entry is None:
            return self.async_abort(reason="reauth_failed")
        self._account = str(entry_data.get(CONF_ACCOUNT, ""))
        return await self.async_step_user()

    async def _prepare_discovery(self) -> ConfigFlowResult:
        """Validate the SmartHome token by fetching the initial snapshot."""

        if self._session is None:
            return self.async_abort(reason="cannot_connect")
        try:
            self._snapshot = await self._api().async_get_snapshot(self._session)
        except (SmartHomeApiError, InvalidProtocolDataError) as error:
            _LOGGER.warning(
                "Huawei SmartHome discovery failed: %s",
                type(error).__name__,
            )
            return self.async_abort(reason="cannot_connect")
        if not self._snapshot.homes:
            return await self._async_create_entry(())
        return await self.async_step_home()

    async def _async_create_entry(self, selected: tuple[str, ...]) -> ConfigFlowResult:
        """Persist credentials and create or update the config entry."""

        if self._session is None or self._identity is None:
            return self.async_abort(reason="cannot_connect")
        await self.async_set_unique_id(self._session.user_id)
        if self._reauth_entry is not None:
            self._abort_if_unique_id_mismatch()
        else:
            self._abort_if_unique_id_configured()
        await HomeAssistantCredentialStore(self.hass).async_save(self._session)
        data = {
            CONF_ACCOUNT: self._session.account,
            CONF_USER_ID: self._session.user_id,
            CONF_IDENTITY_FINGERPRINT: str(self._identity["identity_fingerprint"]),
            CONF_SELECTED_HOME_IDS: list(selected),
        }
        if self._reauth_entry is not None:
            return self.async_update_reload_and_abort(
                self._reauth_entry,
                title=self._session.account,
                data=data,
            )
        return self.async_create_entry(
            title=self._session.account,
            data=data,
        )

    def _api(self) -> SmartHomeDiscoveryApi:
        """Build the discovery client on Home Assistant's shared session."""

        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        return SmartHomeDiscoveryApi(
            transport=AiohttpHttpTransport(async_get_clientsession(self.hass))
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Return the remote-home selection flow."""

        return HuaweiSmartHomeOptionsFlow(config_entry)


def _home_schema(options: Mapping[str, str]) -> vol.Schema:
    """Build a multi-home selector."""

    return vol.Schema({vol.Required(CONF_SELECTED_HOME_IDS): cv.multi_select(options)})


class HuaweiSmartHomeOptionsFlow(config_entries.OptionsFlow):
    """Change the remote-home discovery scope."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._snapshot: RemoteDiscoverySnapshot | None = None

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Fetch homes and save the selected scope."""

        if self._snapshot is None:
            account = self._config_entry.data.get(CONF_ACCOUNT)
            fingerprint = self._config_entry.data.get(CONF_IDENTITY_FINGERPRINT)
            if not isinstance(account, str) or not account:
                return self.async_abort(reason="cannot_connect")
            try:
                session = await HomeAssistantCredentialStore(self.hass).async_load(
                    account,
                    identity_fingerprint=fingerprint
                    if isinstance(fingerprint, str)
                    else None,
                )
                if session is None or not session.is_hms_valid():
                    return self.async_abort(reason="cannot_connect")
                self._snapshot = await self._api().async_get_snapshot(session)
            except (SmartHomeApiError, InvalidProtocolDataError, ValueError) as error:
                _LOGGER.warning(
                    "Huawei SmartHome options discovery failed: %s",
                    type(error).__name__,
                )
                return self.async_abort(reason="cannot_connect")
        options = {home.home_id: home.name for home in self._snapshot.homes}
        if user_input is None:
            return self.async_show_form(
                step_id="init",
                data_schema=_home_schema(options),
            )
        selected = [
            str(value)
            for value in user_input.get(CONF_SELECTED_HOME_IDS, ())
            if str(value) in options
        ]
        if options and not selected:
            return self.async_show_form(
                step_id="init",
                data_schema=_home_schema(options),
                errors={"base": "home_required"},
            )
        return self.async_create_entry(
            title="",
            data={CONF_SELECTED_HOME_IDS: selected},
        )

    def _api(self) -> SmartHomeDiscoveryApi:
        """Build the discovery API on Home Assistant's shared client."""

        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        return SmartHomeDiscoveryApi(
            transport=AiohttpHttpTransport(async_get_clientsession(self.hass))
        )

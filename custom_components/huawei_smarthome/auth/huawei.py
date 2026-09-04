"""Huawei SmartHome account authentication implementation."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import json
import re
import time
import uuid
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from ..api.transport import HttpResponse
from ..const import (
    ACCOUNT_BASE_URL,
    HMS_LITE_TOKEN_PATH,
    OAUTH_BASE_URL,
    SMART_HOME_ACCOUNT_CLIENT_VERSION,
    SMART_HOME_ACCOUNT_USER_AGENT,
    SMART_HOME_ACCOUNT_VERSION,
    SMART_HOME_APP_ID,
    SMART_HOME_BASE_URL,
    SMART_HOME_IOS_APP_ID,
    SMART_HOME_OAUTH_CLIENT_ID,
    SMART_HOME_USER_AGENT,
)
from ..errors import (
    AuthenticationError,
    InvalidCredentialsError,
    TransientAuthenticationError,
)
from ..domain.models import AuthSession
from .interface import LoginChallenge, LoginStart


SCOPE_FOR_CODE = (
    "openid https://www.huawei.com/auth/account/accountlist "
    "https://www.huawei.com/auth/account/birthday "
    "https://www.huawei.com/auth/account/base.profile"
)
SCOPE_FOR_SESSION = (
    "openid https://www.huawei.com/auth/account/mobile.number email "
    "https://www.huawei.com/auth/account/accountlist "
    "https://www.huawei.com/auth/account/base.profile"
)


@dataclass(frozen=True, slots=True)
class _PendingLogin:
    account: str
    encrypted_password: str
    challenge_name: str
    challenge_type: str


class HuaweiSmartHomeAuthProvider:
    """Interactive provider for the verified SmartHome login sequence."""

    def __init__(
        self,
        *,
        device_id: str,
        device_name: str,
        pushtmid: str | None = None,
        identity_fingerprint: str | None = None,
        timeout: float = 20.0,
        transport: Any | None = None,
    ) -> None:
        if not device_id:
            raise ValueError("device_id is required")
        self.device_id = device_id
        self.device_name = device_name or "huawei-smarthome"
        self.pushtmid = pushtmid
        self.identity_fingerprint = identity_fingerprint
        self.timeout = timeout
        self._transport = transport or _urllib_transport
        self._cookies: dict[str, str] = {}
        self._pending: _PendingLogin | None = None

    async def async_begin_login(self, account: str, password: str) -> LoginStart:
        """Start login and return either a session or a device challenge."""

        account = account.strip()
        if not account or not password:
            raise InvalidCredentialsError("account and password are required")
        return await asyncio.to_thread(self._begin_login, account, password)

    async def async_complete_challenge(self, code: str) -> AuthSession:
        """Submit a pending challenge code."""

        if not code.strip():
            raise InvalidCredentialsError("challenge code is required")
        try:
            return await asyncio.to_thread(self._complete_challenge, code.strip())
        finally:
            self._pending = None

    async def async_refresh_oauth(self, session: AuthSession) -> AuthSession:
        """Refresh the OAuth session access token using the service token."""

        return await asyncio.to_thread(self._refresh_oauth, session)

    async def async_refresh_hms_lite(self, session: AuthSession) -> AuthSession:
        """Reissue HMS-lite credentials through a silent OAuth code."""

        return await asyncio.to_thread(self._refresh_hms_lite, session)

    def _refresh_oauth(self, session: AuthSession) -> AuthSession:
        if not session.service_token:
            raise AuthenticationError("Huawei SmartHome service token is unavailable")
        response = self._oauth_request(
            need_code=False,
            scope=SCOPE_FOR_SESSION,
            service_token=session.service_token,
        )
        if response.status == 429 or response.status >= 500:
            raise TransientAuthenticationError(
                "Huawei SmartHome OAuth session refresh is temporarily unavailable"
            )
        payload = _json_object(response.body)
        access_token = _find_string(payload, "access_token")
        expires_at = _expires_at(payload.get("expire_in"))
        if response.status >= 400 or not access_token or expires_at is None:
            raise AuthenticationError("Huawei SmartHome OAuth session refresh failed")
        return replace(
            session,
            oauth_access_token=access_token,
            oauth_expires_at=expires_at,
            generation=session.generation + 1,
        )

    def _refresh_hms_lite(self, session: AuthSession) -> AuthSession:
        if not session.service_token:
            raise AuthenticationError("Huawei SmartHome service token is unavailable")
        code = self._obtain_silent_code(session.service_token)
        access_token, refresh_token, expires_at = self._exchange_hms_lite_code(
            session.user_id,
            code,
        )
        return replace(
            session,
            hms_access_token=access_token,
            hms_refresh_token=refresh_token or session.hms_refresh_token,
            hms_expires_at=expires_at,
        )

    def _begin_login(self, account: str, password: str) -> LoginStart:
        self._cookies.clear()
        self._pending = None
        public_key = self._fetch_rsa_public_key()
        encrypted_password = _encrypt_password(password, public_key)
        response = self._login_request(
            account,
            encrypted_password,
            challenge=None,
            retry=False,
        )
        fields = _parse_form(response.body)
        result_code = _first(fields, "resultCode")
        if response.status < 400 and result_code == "0":
            return LoginStart(session=self._finish_login(account, fields))

        challenge = _extract_challenge(fields)
        if challenge is None:
            raise InvalidCredentialsError("Huawei SmartHome account login rejected")
        challenge_name, challenge_type = challenge
        self._pending = _PendingLogin(
            account=account,
            encrypted_password=encrypted_password,
            challenge_name=challenge_name,
            challenge_type=challenge_type,
        )
        return LoginStart(
            challenge=LoginChallenge(
                prompt="请在另一台华为设备上查看挑战码",
                challenge_name=challenge_name,
                challenge_type=challenge_type,
            )
        )

    def _complete_challenge(self, code: str) -> AuthSession:
        pending = self._pending
        if pending is None:
            raise InvalidCredentialsError("no pending Huawei SmartHome challenge")
        response = self._login_request(
            pending.account,
            pending.encrypted_password,
            challenge=(code, pending.challenge_name, pending.challenge_type),
            retry=True,
        )
        fields = _parse_form(response.body)
        if response.status >= 400 or _first(fields, "resultCode") != "0":
            raise InvalidCredentialsError("Huawei SmartHome challenge rejected")
        return self._finish_login(pending.account, fields)

    def _finish_login(
        self,
        account: str,
        fields: Mapping[str, list[str]],
    ) -> AuthSession:
        service_token = _first(fields, "TGC")
        user_id = _first(fields, "userID")
        if not service_token or not user_id:
            raise AuthenticationError("login response did not contain a session")

        st_response = self._post_account_form(
            "/AccountServer/IUserInfoMng/stAuth",
            {
                "ver": SMART_HOME_ACCOUNT_VERSION,
                "st": service_token,
                "app": SMART_HOME_APP_ID,
                "agr": "1",
                "chg": "0",
                "clT": "54",
                "cn": "54000000",
                "dS": "0",
                "dvID": self.device_id,
                "dvT": "6",
                "gAc": "0",
                "tmT": "iPhone",
            },
        )
        st_fields = _parse_form(st_response.body)
        if st_response.status >= 400 or _first(st_fields, "resultCode") not in (
            None,
            "",
            "0",
        ):
            raise AuthenticationError("stAuth session validation failed")

        self._post_user_info(user_id)
        code = self._obtain_silent_code(service_token)

        session_response = self._oauth_request(
            need_code=False,
            scope=SCOPE_FOR_SESSION,
            service_token=service_token,
        )
        session_payload = _json_object(session_response.body)
        oauth_access_token = _find_string(session_payload, "access_token")
        if session_response.status >= 400 or not oauth_access_token:
            raise AuthenticationError("OAuth session exchange failed")

        hms_access_token, hms_refresh_token, hms_expires_at = (
            self._exchange_hms_lite_code(user_id, code)
        )
        return AuthSession(
            account=account,
            user_id=user_id,
            service_token=service_token,
            hms_access_token=hms_access_token,
            hms_refresh_token=(
                hms_refresh_token if isinstance(hms_refresh_token, str) else None
            ),
            hms_expires_at=hms_expires_at,
            oauth_access_token=oauth_access_token,
            oauth_expires_at=_expires_at(session_payload.get("expire_in")),
            device_id=self.device_id,
            device_name=self.device_name,
            pushtmid=self.pushtmid,
            identity_fingerprint=self.identity_fingerprint,
            app_id=SMART_HOME_IOS_APP_ID,
            base_url=SMART_HOME_BASE_URL,
            home_zone=_first(st_fields, "homeZone"),
            oauth_domain=_first(st_fields, "oauthDomain"),
            site_domain=_first(st_fields, "siteDomain"),
        )

    def _obtain_silent_code(self, service_token: str) -> str:
        response = self._oauth_request(
            need_code=True,
            scope=SCOPE_FOR_CODE,
            service_token=service_token,
        )
        if response.status == 429 or response.status >= 500:
            raise TransientAuthenticationError(
                "Huawei SmartHome OAuth code request is temporarily unavailable"
            )
        payload = _json_object(response.body)
        code = _find_string(payload, "code")
        if response.status >= 400 or not code:
            raise AuthenticationError("OAuth code exchange failed")
        return code

    def _exchange_hms_lite_code(
        self,
        user_id: str,
        code: str,
    ) -> tuple[str, str | None, datetime | None]:
        response = self._request(
            "POST",
            f"{SMART_HOME_BASE_URL}{HMS_LITE_TOKEN_PATH}",
            {
                "Accept": "*/*",
                "Accept-Language": "zh-Hans-CN;q=1",
                "Authorization": "Bearer (null)",
                "Content-Type": "application/json;charset=UTF-8",
                "X-AppId": SMART_HOME_IOS_APP_ID,
                "X-Huid": user_id,
                "X-RequestId": str(uuid.uuid4()).upper(),
                "User-Agent": SMART_HOME_USER_AGENT,
            },
            json.dumps(
                {
                    "appId": SMART_HOME_OAUTH_CLIENT_ID,
                    "code": quote(code, safe=""),
                },
                separators=(",", ":"),
            ).encode("utf-8"),
            send_cookies=False,
        )
        if response.status == 429 or response.status >= 500:
            raise TransientAuthenticationError(
                "Huawei SmartHome HMS-lite token exchange is temporarily unavailable"
            )
        payload = _json_object(response.body)
        access_token = payload.get("access_token")
        if response.status >= 400 or not isinstance(access_token, str):
            raise AuthenticationError("HMS-lite token exchange failed")
        refresh_token = payload.get("refresh_token")
        return (
            access_token,
            refresh_token if isinstance(refresh_token, str) else None,
            _expires_at(payload.get("expires_in")),
        )

    def _fetch_rsa_public_key(self) -> str:
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<GetResourceReq>"
            f"<version>{SMART_HOME_ACCOUNT_VERSION}</version>"
            "<resourceID>upLogin</resourceID>"
            "<reqClientType>54</reqClientType>"
            "<languageCode>zh-Hans-CN</languageCode>"
            "</GetResourceReq>"
        ).encode("utf-8")
        response = self._post_account(
            "/AccountServer/IUserInfoMng/getResource",
            body,
            "text/xml; charset=utf-8",
        )
        key = _public_key_from_response(response.body)
        if response.status >= 400 or not key:
            raise AuthenticationError("RSA resource lookup failed")
        return key

    def _login_request(
        self,
        account: str,
        encrypted_password: str,
        *,
        challenge: tuple[str, str, str] | None,
        retry: bool,
    ) -> HttpResponse:
        params: list[tuple[str, str]] = [
            ("ver", SMART_HOME_ACCOUNT_VERSION),
            ("acT", "2"),
            ("ac", account),
            ("pw", encrypted_password),
            ("dvT", "6"),
            ("dvID", self.device_id),
            ("tmT", "iPhone"),
            ("clT", "54"),
            ("cn", "54000000"),
            ("os", "iOS15.8.8"),
            ("app", SMART_HOME_APP_ID),
            ("dvN", self.device_name),
            ("uuid", self.device_id),
        ]
        if challenge:
            code, name, account_type = challenge
            params.extend(
                [("vCode", code), ("vAcT", account_type), ("vAc", name)]
            )
        params.extend(
            [
                ("lang", "zh-Hans-CN"),
                ("dS", "0"),
                ("mA", "1" if retry else "0"),
                ("deviceInfo", json.dumps(self._device_info(), separators=(",", ":"))),
            ]
        )
        return self._post_account(
            "/AccountServer/IDM/loginV3",
            urlencode(params).encode("utf-8"),
            "application/x-www-form-urlencoded; charset=UTF-8",
        )

    def _post_user_info(self, user_id: str) -> None:
        root = ElementTree.Element("GetUserInfoReq")
        for name, value in (
            ("version", SMART_HOME_ACCOUNT_VERSION),
            ("userID", user_id),
            ("reqClientType", "54"),
            ("queryRangeFlag", "00100000"),
            ("cliDataVersion", f"{int(time.time() * 1000)}_rp"),
            ("cliDataRangeFlag", "11110010"),
        ):
            ElementTree.SubElement(root, name).text = value
        info = ElementTree.SubElement(root, "deviceInfo")
        for name, value in self._device_info().items():
            ElementTree.SubElement(info, name).text = str(value)
        response = self._post_account(
            "/AccountServer/IUserInfoMng/getUserInfo",
            ElementTree.tostring(root, encoding="utf-8", xml_declaration=True),
            "text/xml; charset=utf-8",
        )
        if response.status >= 400:
            raise AuthenticationError("user information lookup failed")

    def _oauth_request(
        self,
        *,
        need_code: bool,
        scope: str,
        service_token: str,
    ) -> HttpResponse:
        body = urlencode(
            [
                ("grant_type", "service_token"),
                ("scope", scope),
                ("service_token", service_token),
                ("device_type", "6"),
                ("package_name", SMART_HOME_APP_ID),
                ("siteId", "1"),
                ("device_id", self.device_id),
                ("need_code", "true" if need_code else "false"),
                ("uuid", self.device_id),
            ]
        ).encode("utf-8")
        query = urlencode(
            {
                "client_id": SMART_HOME_OAUTH_CLIENT_ID,
                "Version": SMART_HOME_ACCOUNT_VERSION,
                "cVersion": SMART_HOME_ACCOUNT_CLIENT_VERSION,
                "srcAppName": SMART_HOME_APP_ID,
            }
        )
        return self._request(
            "POST",
            f"{OAUTH_BASE_URL}/oauth2/v3/silent_token?{query}",
            {
                "Accept": "*/*",
                "Accept-Language": "zh-CN,zh-Hans;q=0.9",
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "terminal-type": "iPhone",
                "User-Agent": SMART_HOME_ACCOUNT_USER_AGENT,
            },
            body,
            send_cookies=False,
        )

    def _post_account_form(
        self,
        path: str,
        values: Mapping[str, str],
    ) -> HttpResponse:
        return self._post_account(
            path,
            urlencode(values).encode("utf-8"),
            "application/x-www-form-urlencoded; charset=UTF-8",
        )

    def _post_account(self, path: str, body: bytes, content_type: str) -> HttpResponse:
        query = urlencode(
            {
                "Version": SMART_HOME_ACCOUNT_VERSION,
                "cVersion": SMART_HOME_ACCOUNT_CLIENT_VERSION,
                "ctrID": uuid.uuid4().hex,
                "srcAppName": SMART_HOME_APP_ID,
            }
        )
        url = f"{ACCOUNT_BASE_URL}{path}?{query}"
        return self._request(
            "POST",
            url,
            {
                "Accept": "*/*",
                "Accept-Language": "zh-CN,zh-Hans;q=0.9",
                "Authorization": str(int(time.time() * 1000)),
                "Content-Type": content_type,
                "SOAPAction": url,
                "User-Agent": SMART_HOME_ACCOUNT_USER_AGENT,
            },
            body,
        )

    def _request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        *,
        send_cookies: bool = True,
    ) -> HttpResponse:
        request_headers = dict(headers)
        if send_cookies and self._cookies:
            request_headers["Cookie"] = "; ".join(
                f"{name}={value}" for name, value in self._cookies.items()
            )
        try:
            result = self._transport(
                method,
                url,
                request_headers,
                body,
                self.timeout,
            )
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise TransientAuthenticationError(
                "Huawei SmartHome authentication transport failed"
            ) from error
        if not isinstance(result, HttpResponse):
            raise AuthenticationError("authentication transport returned an invalid response")
        for name, value in result.headers.items():
            if name.lower() == "set-cookie":
                pair = value.split(";", 1)[0]
                cookie_name, separator, cookie_value = pair.partition("=")
                if separator and cookie_name and cookie_value:
                    self._cookies[cookie_name.strip()] = cookie_value
        return result

    def _device_info(self) -> dict[str, str | int]:
        return {
            "terminalCategory": 9,
            "deviceType": 6,
            "deviceID": self.device_id,
            "terminalType": "iPhone",
            "deviceAliasName": self.device_name,
            "uuid": self.device_id,
        }


def _urllib_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes | None,
    timeout: float,
) -> HttpResponse:
    """Perform one synchronous request for the worker thread."""

    request = Request(url, data=body, headers=dict(headers), method=method)
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


def _first(fields: Mapping[str, list[str]], key: str) -> str | None:
    values = fields.get(key)
    return values[0] if values else None


def _parse_form(body: bytes) -> dict[str, list[str]]:
    return parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)


def _extract_challenge(fields: Mapping[str, list[str]]) -> tuple[str, str] | None:
    raw = _first(fields, "errorDesc")
    if not raw:
        return None
    try:
        details = json.loads(raw)
    except json.JSONDecodeError:
        return None
    items = details.get("authCodeSentList") if isinstance(details, dict) else None
    if not isinstance(items, list):
        return None
    selected = next(
        (
            item
            for item in items
            if isinstance(item, dict) and str(item.get("sent")) == "1"
        ),
        next((item for item in items if isinstance(item, dict)), None),
    )
    if not isinstance(selected, dict):
        return None
    name = selected.get("name")
    account_type = selected.get("accountType")
    if not isinstance(name, str) or account_type is None:
        return None
    return name, str(account_type)


def _json_object(body: bytes) -> dict[str, Any]:
    try:
        value = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AuthenticationError("Huawei SmartHome response is not JSON") from error
    if not isinstance(value, dict):
        raise AuthenticationError("Huawei SmartHome response is not an object")
    return value


def _find_string(value: Any, wanted: str) -> str | None:
    if isinstance(value, dict):
        candidate = value.get(wanted)
        if isinstance(candidate, str) and candidate:
            return candidate
        for child in value.values():
            found = _find_string(child, wanted)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_string(child, wanted)
            if found:
                return found
    return None


def _expires_at(value: Any) -> datetime | None:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def _encrypt_password(password: str, public_key_pem: str) -> str:
    public_key = serialization.load_pem_public_key(public_key_pem.encode("ascii"))
    if not isinstance(public_key, rsa.RSAPublicKey):
        raise AuthenticationError("RSA resource did not contain an RSA public key")
    encrypted = public_key.encrypt(
        password.encode("utf-8"),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return encrypted.hex().upper()


def _public_key_from_response(body: bytes) -> str | None:
    try:
        value = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        value = None
    if value is not None:
        found = _find_public_key(value)
        if found:
            return found
    try:
        root = ElementTree.fromstring(body.decode("utf-8"))
    except (UnicodeDecodeError, ElementTree.ParseError):
        return None
    for element in root.iter():
        text = (element.text or "").strip()
        if not text:
            continue
        found = _normalize_public_key(text)
        if found:
            return found
        try:
            nested = json.loads(text)
        except json.JSONDecodeError:
            continue
        found = _find_public_key(nested)
        if found:
            return found
    return None


def _find_public_key(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower().replace("_", "-")
            if isinstance(child, str) and any(
                marker in lowered
                for marker in ("public-key", "publickey", "rsapublic", "rsa-key")
            ):
                found = _normalize_public_key(child)
                if found:
                    return found
            found = _find_public_key(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_public_key(child)
            if found:
                return found
    return None


def _normalize_public_key(value: str) -> str | None:
    text = value.strip()
    if "BEGIN PUBLIC KEY" in text or "BEGIN RSA PUBLIC KEY" in text:
        return text
    compact = re.sub(r"\s+", "", text)
    try:
        der = base64.b64decode(compact, validate=True)
        public_key = serialization.load_der_public_key(der)
    except (ValueError, TypeError, UnicodeEncodeError):
        return None
    if not isinstance(public_key, rsa.RSAPublicKey):
        return None
    return public_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")

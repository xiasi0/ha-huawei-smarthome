"""Shared Huawei SmartHome exceptions."""

from __future__ import annotations


class HuaweiSmartHomeError(Exception):
    """Base exception for the integration."""


class InvalidProtocolDataError(HuaweiSmartHomeError):
    """A remote response could not be normalized safely."""


class AuthenticationError(HuaweiSmartHomeError):
    """Authentication or token exchange failed."""


class InvalidCredentialsError(AuthenticationError):
    """The account or challenge code was rejected."""


class TransientAuthenticationError(AuthenticationError):
    """Authentication transport or service failure that may recover."""


class ReauthenticationRequired(AuthenticationError):
    """The user must authenticate again."""

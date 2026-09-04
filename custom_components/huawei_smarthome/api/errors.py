"""HTTP and remote errors for Huawei SmartHome."""

from __future__ import annotations

from ..errors import HuaweiSmartHomeError


class SmartHomeApiError(HuaweiSmartHomeError):
    """Base error for SmartHome HTTP operations."""


class AuthExpiredError(SmartHomeApiError):
    """The HMS-lite session is expired or invalid."""


class PermissionDeniedError(SmartHomeApiError):
    """The account cannot access the requested resource."""


class RateLimitedError(SmartHomeApiError):
    """The remote service rate-limited a request."""


class InvalidResponseError(SmartHomeApiError):
    """The remote response is not a supported schema."""


class TransientNetworkError(SmartHomeApiError):
    """The request failed due to a retryable network condition."""


class RemoteOperationError(SmartHomeApiError):
    """The remote service returned an operation error."""

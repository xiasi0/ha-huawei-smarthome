"""Small normalized model for public Huawei SmartHome Profiles."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, (Mapping, list, tuple, set)):
        return None
    text = str(value).strip()
    return text or None


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
        return int(number) if number.is_integer() else number
    return None


@dataclass(frozen=True, slots=True)
class ProfileField:
    """One Profile characteristic."""

    name: str
    data_type: str | None = None
    method: str = ""
    permission: str | None = None
    report: bool = False
    unit: str | None = None
    label: str | None = None
    description: str | None = None
    min_value: int | float | None = None
    max_value: int | float | None = None
    step: int | float | None = None
    enum_values: tuple[tuple[str, str | None], ...] = ()

    @property
    def readable(self) -> bool:
        return "R" in self.method.upper() or "G" in (self.permission or "")

    @property
    def writable(self) -> bool:
        return "W" in self.method.upper() or "P" in (self.permission or "")

    @property
    def resolved_step(self) -> int | float | None:
        """Return the declared step or the integral type's natural step."""

        if self.step is not None:
            return self.step
        if (self.data_type or "").strip().lower() in {"int", "integer"}:
            if self.min_value is not None and self.max_value is not None:
                return 1
        return None

    @property
    def enum_options(self) -> tuple[tuple[str, str], ...]:
        """Return unique HA labels paired with their raw Profile values."""

        options: list[tuple[str, str]] = []
        labels: set[str] = set()
        for raw_value, description in self.enum_values:
            label = description or raw_value
            if label in labels:
                label = f"{label} ({raw_value})"
            labels.add(label)
            options.append((label, raw_value))
        return tuple(options)

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "ProfileField | None":
        name = _text(value.get("characteristicName"))
        if not name:
            return None
        enum_values: list[tuple[str, str | None]] = []
        raw_enums = value.get("enumList")
        if isinstance(raw_enums, list):
            for item in raw_enums:
                if not isinstance(item, Mapping):
                    continue
                enum_value = _text(item.get("enumVal"))
                if enum_value is not None:
                    enum_values.append((enum_value, _text(item.get("descCh"))))
        return cls(
            name=name,
            data_type=_text(value.get("characteristicType")),
            method=_text(value.get("method")) or "",
            permission=_text(value.get("permission")),
            report=bool(value.get("report")),
            unit=_text(value.get("unit")),
            label=_text(value.get("attrName")),
            description=_text(value.get("descCh")),
            min_value=_number(value.get("min")),
            max_value=_number(value.get("max")),
            step=_number(value.get("step")),
            enum_values=tuple(enum_values),
        )


@dataclass(frozen=True, slots=True)
class ProfileService:
    """One public Profile service."""

    sid: str
    service_type: str | None
    name: str | None = None
    description: str | None = None
    fields: Mapping[str, ProfileField] = field(default_factory=dict)

    def field(self, name: str) -> ProfileField | None:
        return self.fields.get(name)

    @property
    def kind(self) -> str:
        """Return the normalized service kind used by generic bindings."""

        value = (self.service_type or self.sid).strip().lower()
        return value.rsplit(".", 1)[-1]


@dataclass(frozen=True, slots=True)
class ProductProfile:
    """Normalized product metadata and service definitions."""

    prod_id: str
    model: str | None
    device_name: str | None
    manufacturer: str | None
    ui_type: str | None
    plugin_tag: str | None
    services: Mapping[str, ProfileService] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "ProductProfile":
        prod_id = _text(value.get("prodId"))
        if not prod_id:
            raise ValueError("Profile has no prodId")
        service_map: dict[str, ProfileService] = {}
        raw_services = value.get("services")
        if isinstance(raw_services, list):
            for raw_service in raw_services:
                if not isinstance(raw_service, Mapping):
                    continue
                sid = _text(raw_service.get("serviceId"))
                if not sid:
                    continue
                previous = service_map.get(sid)
                service_type = (
                    _text(raw_service.get("serviceType"))
                    or (previous.service_type if previous is not None else sid)
                )
                fields = dict(previous.fields if previous is not None else {})
                raw_fields = raw_service.get("characteristics")
                if isinstance(raw_fields, list):
                    for raw_field in raw_fields:
                        if not isinstance(raw_field, Mapping):
                            continue
                        field = ProfileField.from_payload(raw_field)
                        if field is not None:
                            fields[field.name] = field
                service_map[sid] = ProfileService(
                    sid=sid,
                    service_type=service_type,
                    name=_text(raw_service.get("serviceName")),
                    description=_text(raw_service.get("descCh")),
                    fields=fields,
                )
        return cls(
            prod_id=prod_id,
            model=_text(value.get("deviceModel")),
            device_name=_text(value.get("deviceName")),
            manufacturer=_text(value.get("manufacturerName")),
            ui_type=_text(value.get("uiType")),
            plugin_tag=_text(value.get("pluginTag")),
            services=service_map,
        )

    def available_services(self, cloud_sids: set[str]) -> tuple[ProfileService, ...]:
        """Return Profile services confirmed by the cloud device list."""

        return tuple(
            service
            for sid, service in self.services.items()
            if sid in cloud_sids
        )


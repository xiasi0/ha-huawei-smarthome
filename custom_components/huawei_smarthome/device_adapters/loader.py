"""Automatic loader for user-contributed product adapter files."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
import pkgutil

from .api import HuaweiProductAdapter


def load_product_adapters() -> dict[str, HuaweiProductAdapter]:
    """Load every ``prod_<prodId>.py`` without editing a registry file."""

    package_name = __package__ or ""
    package_path = Path(__file__).parent
    adapters: dict[str, HuaweiProductAdapter] = {}
    for module_info in pkgutil.iter_modules([str(package_path)]):
        if not module_info.name.startswith("prod_"):
            continue
        module = import_module(f"{package_name}.{module_info.name}")
        adapter = getattr(module, "ADAPTER", None)
        prod_id = getattr(adapter, "prod_id", None)
        if adapter is None or not isinstance(prod_id, str) or not prod_id.strip():
            raise ValueError(
                f"{module_info.name} must expose ADAPTER.prod_id"
            )
        key = prod_id.strip().casefold()
        if key in adapters:
            raise ValueError(f"duplicate product adapter: {prod_id}")
        adapters[key] = adapter
    return adapters

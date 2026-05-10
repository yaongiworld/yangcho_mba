"""Load and query the curated OY brand allowlist.

Single source of truth for "which brands do we want to scrape from OY Global"
and "which of those are LG H&H?". Keeping this as a code module (not just
the YAML) lets the orchestrator and tests import a stable API.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

YAML_PATH = Path(__file__).parent.parent.parent / "data" / "oy_brands.yaml"


@dataclass(frozen=True)
class BrandConfig:
    brand_no: str
    name: str
    is_lg: bool
    note: str = ""


@cache
def load_brands() -> list[BrandConfig]:
    """All curated brands (LG + competitors) flattened into one list.

    Cached for the process lifetime; re-import to pick up YAML edits.
    """
    raw = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
    out: list[BrandConfig] = []
    for section in ("lg", "competitors"):
        for entry in raw.get(section) or []:
            out.append(
                BrandConfig(
                    brand_no=entry["brand_no"],
                    name=entry["name"],
                    is_lg=bool(entry.get("is_lg", False)),
                    note=entry.get("note", ""),
                )
            )
    return out


def lg_brand_nos() -> list[str]:
    """LG-only brand_nos. Use this as `brand_nos` for an LG-only category scrape."""
    return [b.brand_no for b in load_brands() if b.is_lg]


def all_curated_brand_nos() -> list[str]:
    """LG + competitors brand_nos."""
    return [b.brand_no for b in load_brands()]


def is_lg_brand_no(brand_no: str) -> bool:
    return any(b.brand_no == brand_no and b.is_lg for b in load_brands())


def brand_config_by_no(brand_no: str) -> BrandConfig | None:
    for b in load_brands():
        if b.brand_no == brand_no:
            return b
    return None

"""Schema roundtrips and enum parity with the SQL migration."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipeline.schemas import (
    FrictionAnalysis,
    FrictionItem,
    MomentInsert,
    PipelineStage,
    PipelineStatus,
    PlaybookKind,
    ReviewStatus,
    SourceKind,
)


SQL_MIGRATION = Path(__file__).parent.parent.parent / "supabase" / "migrations" / "0001_initial_schema.sql"


@pytest.mark.parametrize(
    "py_enum,sql_type",
    [
        (PipelineStage, "pipeline_stage"),
        (PipelineStatus, "pipeline_status"),
        (SourceKind, "source_kind"),
        (ReviewStatus, "review_status"),
        (PlaybookKind, "playbook_kind"),
    ],
)
def test_enum_parity_with_sql(py_enum, sql_type: str) -> None:
    """Every Python enum must match the corresponding Postgres ENUM."""
    sql = SQL_MIGRATION.read_text(encoding="utf-8")
    m = re.search(rf"CREATE TYPE {sql_type} AS ENUM \(([^)]+)\)", sql)
    assert m, f"could not find CREATE TYPE {sql_type} in migration"
    sql_values = sorted(re.findall(r"'([^']+)'", m.group(1)))
    py_values = sorted(member.value for member in py_enum)
    assert py_values == sql_values, f"{py_enum.__name__} != {sql_type}: py={py_values} sql={sql_values}"


def test_friction_analysis_roundtrip() -> None:
    """FrictionAnalysis serializes to JSON and back without loss — confirms
    parse_or_default() will work end-to-end on real LLM output."""
    fa = FrictionAnalysis(
        frictions=[
            FrictionItem(
                summary="4–6 hr outdoor + UV + sweat",
                mechanism="Film-former breakdown via salt gradient + sebum interaction.",
                efficacy_class="long-wear-film",
            ),
        ],
        self_rating=8,
        self_rating_reasoning="Mechanism is grounded in known rheology.",
    )
    json_str = fa.model_dump_json()
    rehydrated = FrictionAnalysis.model_validate_json(json_str)
    assert rehydrated.self_rating == 8
    assert len(rehydrated.frictions) == 1
    assert rehydrated.frictions[0].efficacy_class == "long-wear-film"


def test_friction_analysis_rejects_empty() -> None:
    """Pydantic should refuse a FrictionAnalysis with zero frictions."""
    with pytest.raises(Exception):  # ValidationError
        FrictionAnalysis(frictions=[], self_rating=5, self_rating_reasoning="")


def test_self_rating_bounds() -> None:
    """self_rating must be 1–10."""
    with pytest.raises(Exception):
        FrictionAnalysis(
            frictions=[FrictionItem(summary="x", mechanism="y")],
            self_rating=11,
            self_rating_reasoning="too high",
        )
    with pytest.raises(Exception):
        FrictionAnalysis(
            frictions=[FrictionItem(summary="x", mechanism="y")],
            self_rating=0,
            self_rating_reasoning="too low",
        )


def test_moment_insert_purchase_intent_bounds() -> None:
    """purchase_intent must be 1–5 if set."""
    # OK at 3
    MomentInsert(
        moment_date=datetime.now(timezone.utc).date(),
        name="x",
        source=SourceKind.REDDIT,
        purchase_intent=3,
        prompt_version="abc",
    )
    # Reject 6
    with pytest.raises(Exception):
        MomentInsert(
            moment_date=datetime.now(timezone.utc).date(),
            name="x",
            source=SourceKind.REDDIT,
            purchase_intent=6,
            prompt_version="abc",
        )

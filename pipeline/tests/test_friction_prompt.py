"""Friction prompt loads, interpolates, and references the 3 hero cases."""

from __future__ import annotations

import pytest

from pipeline.llm import (
    MissingVariableError,
    _interpolate,
    _load_prompt,
    _VAR_RE,
)


def test_friction_prompt_loads() -> None:
    template = _load_prompt("friction")
    assert len(template) > 500


def test_friction_prompt_has_expected_variables() -> None:
    template = _load_prompt("friction")
    refs = set(_VAR_RE.findall(template))
    assert refs == {
        "hero_case_1",
        "hero_case_2",
        "hero_case_3",
        "moment_name",
        "moment_description",
        "signal_sample",
    }


def test_friction_prompt_interpolates_cleanly() -> None:
    template = _load_prompt("friction")
    rendered = _interpolate(
        template,
        {
            "hero_case_1": "<HERO 1>",
            "hero_case_2": "<HERO 2>",
            "hero_case_3": "<HERO 3>",
            "moment_name": "#SundayTailgate",
            "moment_description": "NFL outdoor pre-game tailgating",
            "signal_sample": "- post 1\n- post 2",
        },
    )
    assert "<HERO 1>" in rendered
    assert "<HERO 2>" in rendered
    assert "<HERO 3>" in rendered
    assert "#SundayTailgate" in rendered
    assert "{{" not in rendered  # all handlebars consumed


def test_missing_variable_raises() -> None:
    template = _load_prompt("friction")
    with pytest.raises(MissingVariableError):
        _interpolate(template, {})


def test_all_pipeline_prompts_load() -> None:
    """Every prompt the pipeline references should exist on disk and load cleanly."""
    for name in (
        "friction",
        "scoring",
        "product_match",
        "marketing_post",
        "product_idea",
        "influencer",
        "self_rating",
    ):
        text = _load_prompt(name)
        assert text, f"prompt {name!r} loaded empty"

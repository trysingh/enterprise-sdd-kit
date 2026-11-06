"""ekit 0.6.3: GHERKIN-UI-ENTRY heuristic.

A @ui-tagged scenario with no Background that acts on a page (sends/selects/submits/deletes/
clicks/edits/creates/posts/updates/removes) before it opens/navigates/views/visits/loads one is
flagged warn - each scenario runs from a fresh state, so acting on a page it never entered is
usually a missed step, not real coverage.

This is a heuristic, not a parser: a Background block anywhere in the file is treated (by design,
conservatively) as supplying entry steps for every scenario in that file, without reading its
step text. False negatives are fine; false positives should be rare.

Run: uv run --with pytest --with pyyaml pytest -q"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ekit import checks, gherkin

W = {"dir": "specs/001-demo/features"}


def _ctx(tmp_path):
    project = SimpleNamespace(root=tmp_path, rel=lambda p: str(Path(p).relative_to(tmp_path)))
    return checks.GateContext(project=project, feature_dir=tmp_path / "specs" / "001-demo")


def _write(tmp_path, text: str) -> Path:
    d = tmp_path / "specs/001-demo/features"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "a.feature"
    p.write_text(text, encoding="utf-8")
    return p


def _run(tmp_path, text):
    _write(tmp_path, text)
    return checks.ui_entry_check(_ctx(tmp_path), W)


def test_action_before_entry_warns(tmp_path):
    text = (
        "Feature: Demo\n"
        "  @ui @SCN-001-01\n"
        "  Scenario: edit profile\n"
        "    Given a signed-in user\n"
        "    When the user submits the profile form\n"
        "    Then the profile is updated\n"
    )
    out = _run(tmp_path, text)
    assert len(out) == 1
    assert out[0].level == "warn"
    assert "a.feature:3" in out[0].message
    assert "submits" in out[0].message.lower()


def test_entry_before_action_does_not_warn(tmp_path):
    text = (
        "Feature: Demo\n"
        "  @ui @SCN-001-01\n"
        "  Scenario: edit profile\n"
        "    Given a signed-in user\n"
        "    When the user opens the profile page\n"
        "    And the user submits the profile form\n"
        "    Then the profile is updated\n"
    )
    assert _run(tmp_path, text) == []


def test_background_in_file_suppresses_the_warning(tmp_path):
    text = (
        "Feature: Demo\n"
        "  Background:\n"
        "    Given the user is on the profile page\n\n"
        "  @ui @SCN-001-01\n"
        "  Scenario: edit profile\n"
        "    When the user submits the profile form\n"
        "    Then the profile is updated\n"
    )
    assert _run(tmp_path, text) == []


def test_non_ui_scenario_with_same_shape_does_not_warn(tmp_path):
    text = (
        "Feature: Demo\n"
        "  @SCN-001-01\n"
        "  Scenario: edit profile via API\n"
        "    Given a signed-in user\n"
        "    When the user submits the profile form\n"
        "    Then the profile is updated\n"
    )
    assert _run(tmp_path, text) == []


def test_entry_after_action_still_warns_because_order_matters(tmp_path):
    text = (
        "Feature: Demo\n"
        "  @ui @SCN-001-01\n"
        "  Scenario: edit profile\n"
        "    Given a signed-in user\n"
        "    When the user submits the profile form\n"
        "    And the user opens the profile page\n"
        "    Then the profile is updated\n"
    )
    out = _run(tmp_path, text)
    assert len(out) == 1
    assert out[0].level == "warn"


# ------------------------------------------------------------------ gherkin.py round trip
def test_parse_feature_populates_step_lines_and_has_background(tmp_path):
    p = tmp_path / "a.feature"
    p.write_text(
        "Feature: Demo\n"
        "  Background:\n"
        "    Given a clean database\n\n"
        "  @ui @SCN-001-01\n"
        "  Scenario: edit profile\n"
        "    Given a signed-in user\n"
        "    When the user opens the profile page\n"
        "    And the user submits the profile form\n"
        "    Then the profile is updated\n",
        encoding="utf-8",
    )
    ff = gherkin.parse_feature(p)
    assert ff.has_background is True
    assert len(ff.scenarios) == 1
    s = ff.scenarios[0]
    assert s.steps == 4
    assert s.step_lines == [
        "a signed-in user",
        "the user opens the profile page",
        "the user submits the profile form",
        "the profile is updated",
    ]

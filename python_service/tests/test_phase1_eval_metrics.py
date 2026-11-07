"""Zero denominators and review status must not manufacture human accuracy."""

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evals.runners.run_diagnosis_eval_phase1 import (
    classification_metrics,
    load_candidates,
    metrics,
)


def test_zero_reviewed_denominator_has_null_scores():
    result = metrics([])
    assert result["classification"]["n"] == 0
    assert result["classification"]["accuracy"] is result["classification"]["macro_f1"] is None
    assert result["evidence"]["precision"] is result["unknown_or_abstention"]["rate"] is None


def test_macro_f1_and_confusion_matrix_use_real_counts():
    rows = [{"expected_failure_class": expected, "observed": {"failure_class": actual}}
            for expected, actual in (("runtime_error", "runtime_error"), ("runtime_error", "unknown"), ("unknown", "unknown"))]
    result = classification_metrics(rows)
    assert result["accuracy"] == 2 / 3
    assert result["macro_f1"] == pytest.approx(2 / 3)
    assert result["confusion_matrix"]["runtime_error"]["unknown"] == 1


def test_all_current_candidates_are_pending_and_sources_are_explicit():
    rows = load_candidates()
    assert len(rows) == 40 and all(row["annotation_status"] == "pending_review" for row in rows)
    assert all(row["annotation_source"] and row["source_ref"] for row in rows)
    assert sum(row["source_type"] == "synthetic_adversarial" for row in rows) == 34


def test_codex_annotation_cannot_be_counted_as_independent_human_review(tmp_path):
    row = deepcopy(load_candidates()[0])
    row.update(annotation_status="human_reviewed", reviewer="invented reviewer", reviewed_at="2026-11-07")
    path = tmp_path / "invalid.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="independent"):
        load_candidates(path)

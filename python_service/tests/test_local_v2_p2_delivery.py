"""Delivery integrity guards, using copied public files and no target execution."""
from copy import deepcopy
import json
from pathlib import Path
import zipfile

import pytest

from scripts.check_p2_delivery import ROOT, check, file_set, make_catalog, safe_file
from scripts.package_p2_delivery import safe_member, write_archive


@pytest.fixture
def candidate(tmp_path):
    root = tmp_path / "r"
    for relative in file_set(ROOT):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / relative).read_bytes())
    return root


def test_delivery_audit_is_read_only_and_retains_formal_blockers(candidate):
    catalog = make_catalog(candidate)
    before = {x: safe_file(candidate, x).read_bytes() for x in catalog["files"]}
    result = check(candidate, catalog)
    assert result["result"] == "passed" and len(result["remaining"]) == 4
    assert before == {x: safe_file(candidate, x).read_bytes() for x in catalog["files"]}


def test_changed_driver_is_rejected_against_locked_catalog(candidate):
    catalog = make_catalog(candidate)
    path = candidate / "python_service/scripts/verify_p2_local.py"
    path.write_bytes(path.read_bytes() + b"\n# changed\n")
    with pytest.raises(ValueError, match="DELIVERY_FILE_HASH_MISMATCH"):
        check(candidate, catalog)


def test_new_catalog_does_not_hide_stale_historical_evidence(candidate):
    path = candidate / "docs/verification/p2/protected_validation.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["overlay_hashes"]["driver"] = "0" * 64
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="P2_OVERLAY_EVIDENCE_STALE"):
        check(candidate, make_catalog(candidate))


def test_formal_pass_cannot_be_inferred_from_technical_matrix(candidate):
    path = candidate / "docs/verification/p2/acceptance_matrix.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["overall_result"] = "passed"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="UNCONFIRMED_FORMAL_ACCEPTANCE"):
        check(candidate, make_catalog(candidate))


def test_unlisted_private_file_cannot_be_added_to_candidate(candidate):
    catalog = deepcopy(make_catalog(candidate))
    catalog["files"][".env"] = "0" * 64
    with pytest.raises(ValueError, match="DELIVERY_FILE_SET_MISMATCH"):
        check(candidate, catalog)


@pytest.mark.parametrize("name", ["../outside.txt", "b/.interop/private.json", "C:/private.txt", "b/.env"])
def test_archive_rejects_private_or_escaping_paths(name):
    with pytest.raises(ValueError):
        safe_member(name)


def test_archive_is_deterministic_and_never_overwrites(tmp_path):
    data = {"b/public.json": b"{}\n", "RECEIVER.txt": b"public only\n"}
    first, second = tmp_path / "first.zip", tmp_path / "second.zip"
    write_archive(first, data)
    write_archive(second, data)
    assert first.read_bytes() == second.read_bytes()
    assert set(zipfile.ZipFile(first).namelist()) == set(data)
    with pytest.raises(ValueError, match="ARCHIVE_ALREADY_EXISTS"):
        write_archive(first, data)

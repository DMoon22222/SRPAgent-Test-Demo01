"""Read-only P2 delivery/evidence integrity checks; no Docker, model or Git writes."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

from reliable_codegen.contracts import ContractRegistry
from reliable_codegen.guards import check_public
from reliable_codegen.utils import canonical, digest

if __package__:
    from .verify_p2_local import require, validate_bundle
else:
    from verify_p2_local import require, validate_bundle

ROOT = Path(__file__).resolve().parents[2]
CATALOG = "docs/integration/p2_delivery_files.json"
PHASES = {"bootstrap": ("checks", 8), "lineage": ("cases", 11), "boundaries": ("cases", 25), "protected": ("cases", 6)}
TOOL_FILES = (
    "python_service/scripts/check_p2_delivery.py", "python_service/scripts/package_p2_delivery.py",
    "python_service/scripts/smoke_p2_consumer.py", "python_service/tests/test_local_v2_p2_delivery.py",
)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_file(root, relative):
    require(isinstance(relative, str) and "\\" not in relative and ":" not in relative, "UNSAFE_DELIVERY_PATH")
    parts = PurePosixPath(relative).parts
    require(bool(parts) and not PurePosixPath(relative).is_absolute() and ".." not in parts, "UNSAFE_DELIVERY_PATH")
    require(all(not x.startswith(".") or relative == ".gitattributes" for x in parts), "PRIVATE_DELIVERY_PATH")
    path = (Path(root) / relative).resolve()
    require(path.is_relative_to(Path(root).resolve()), "DELIVERY_PATH_OUTSIDE_ROOT")
    return path


def file_set(root):
    files = {".gitattributes", "docs/integration/config.b-local.p2.example.json", "docs/integration/p2_handoff_manifest.json",
             "docs/integration/p2_external_dependencies.json", "docs/contracts/v2/capabilities.json", "docs/contracts/v2/local_samples.json",
             "docs/verification/local_v2_validation.json", "docs/verification/local_v2_tests.json", "docs/verification/local_v2_wheel.json",
             "docs/verification/local_v2_publication.json", "docs/verification/p2/acceptance_matrix.json", *TOOL_FILES}
    p1 = load(Path(root) / "docs/verification/local_v2_validation.json")
    files.update("python_service/" + relative for relative in p1["source_hashes"])
    for phase in PHASES:
        files.update((f"docs/verification/p2/{phase}_validation.json", f"docs/verification/p2/{phase}_tests.json",
                      f"python_service/scripts/verify_p2_{'local' if phase == 'bootstrap' else phase}.py",
                      f"python_service/tests/test_local_v2_p2{'' if phase == 'bootstrap' else '_' + phase}.py"))
    return files


def make_catalog(root):
    files = {relative: sha(safe_file(root, relative)) for relative in sorted(file_set(root))}
    manifest = load(Path(root) / "docs/integration/p2_handoff_manifest.json")
    return {"record_version": "1.0", "scope": "P2 technical tools/public evidence snapshot; formal acceptance pending",
            "implementation_version": manifest["implementation_version"], "runtime_revision": manifest["source"]["revision"],
            "publication": "local_uncommitted_candidate", "files": files, "files_canonical_sha256": digest(canonical(files))}


def check(root=ROOT, catalog=None):
    root = Path(root).resolve()
    catalog = catalog or load(root / CATALOG)
    require(set(catalog["files"]) == file_set(root), "DELIVERY_FILE_SET_MISMATCH")
    require(catalog["files_canonical_sha256"] == digest(canonical(catalog["files"])), "DELIVERY_CATALOG_HASH_MISMATCH")
    for relative, expected in catalog["files"].items():
        require(sha(safe_file(root, relative)) == expected, "DELIVERY_FILE_HASH_MISMATCH")
    config = load(root / "docs/integration/config.b-local.p2.example.json")
    manifest = load(root / "docs/integration/p2_handoff_manifest.json")
    validate_bundle(config, manifest, ContractRegistry())
    require(catalog["runtime_revision"] == manifest["source"]["revision"], "DELIVERY_RUNTIME_REVISION_MISMATCH")
    require(catalog["implementation_version"] == manifest["implementation_version"], "DELIVERY_VERSION_MISMATCH")
    p1 = load(root / "docs/verification/local_v2_validation.json")
    for relative, expected in p1["source_hashes"].items():
        require(sha(safe_file(root, "python_service/" + relative)) == expected, "P1_SOURCE_SNAPSHOT_MISMATCH")
    summaries = {}
    for phase, (field, count) in PHASES.items():
        value = load(root / f"docs/verification/p2/{phase}_validation.json")
        check_public(value)
        require(value["result"] == "passed" and len(value[field]) == count, "P2_CASE_COVERAGE_MISMATCH")
        identities = [x.get("name", x.get("scenario")) for x in value[field]]
        require(len(set(identities)) == count and all(x["result"] == "passed" for x in value[field]), "P2_CASE_IDENTITY_MISMATCH")
        require(value["source_revision"] == manifest["source"]["revision"] and value["public_contract_sha256"] == manifest["public_contract_sha256"], "P2_BASELINE_MISMATCH")
        require(value["formal_p2_acceptance"] == "blocked" and value["o_receipt"] == "not_received", "UNCONFIRMED_FORMAL_ACCEPTANCE")
        paths = {"config": "docs/integration/config.b-local.p2.example.json", "manifest": "docs/integration/p2_handoff_manifest.json",
                 "bootstrap_driver": "python_service/scripts/verify_p2_local.py", "dependencies": "docs/integration/p2_external_dependencies.json",
                 "driver": f"python_service/scripts/verify_p2_{'local' if phase == 'bootstrap' else phase}.py",
                 "tests": f"python_service/tests/test_local_v2_p2{'' if phase == 'bootstrap' else '_' + phase}.py",
                 "lineage_driver": "python_service/scripts/verify_p2_lineage.py", "lineage_tests": "python_service/tests/test_local_v2_p2_lineage.py",
                 "boundary_driver": "python_service/scripts/verify_p2_boundaries.py"}
        for role, expected in value["overlay_hashes"].items():
            require(role in paths and sha(root / paths[role]) == expected, "P2_OVERLAY_EVIDENCE_STALE")
        tests = load(root / f"docs/verification/p2/{phase}_tests.json")
        check_public(tests)
        require(tests["result"] == "passed" and tests["counts"]["failures"] == tests["counts"]["errors"] == 0, "P2_TEST_RECORD_FAILED")
        summaries[phase] = count
    latest = load(root / "docs/verification/p2/protected_tests.json")
    for relative, expected in latest["test_source_hashes"].items():
        require(sha(safe_file(root, "python_service/tests/" + relative)) == expected, "P2_TEST_SOURCE_STALE")
    matrix = load(root / "docs/verification/p2/acceptance_matrix.json")
    dependencies = load(root / "docs/integration/p2_external_dependencies.json")
    require(all(x["status"] == "passed" for x in matrix["items"] if not x["id"].startswith("formal.")), "P2_TECHNICAL_ITEM_INCOMPLETE")
    remaining = [x["id"] for x in matrix["items"] if x["status"] != "passed"]
    require(len(remaining) == 4 and all(x.startswith("formal.") for x in remaining) and matrix["overall_result"] == "blocked", "UNCONFIRMED_FORMAL_ACCEPTANCE")
    require(dependencies["formal_acceptance"] == "blocked" and all(x["provided_ref"] is None for x in dependencies["items"]), "UNCONFIRMED_EXTERNAL_RECEIPT")
    for relative in catalog["files"]:
        if relative.endswith(".json"):
            check_public(load(root / relative))
    return {"result": "passed", "files_checked": len(catalog["files"]), "runtime_version": manifest["implementation_version"],
            "phase_case_counts": summaries, "latest_recorded_tests": latest["counts"], "formal_p2_acceptance": "blocked",
            "remaining": remaining, "snapshot_sha256": catalog["files_canonical_sha256"],
            "scope": "Read-only evidence/source integrity; does not rerun historical tests, Docker or models"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    result = check(args.root)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

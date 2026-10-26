"""Create a local allowlisted P2 archive; no upload, Git mutation or execution."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

if __package__:
    from .check_p2_delivery import ROOT, CATALOG, check, load, safe_file, sha
    from .verify_p2_local import require
else:
    from check_p2_delivery import ROOT, CATALOG, check, load, safe_file, sha
    from verify_p2_local import require


def safe_member(name):
    require("\\" not in name and ":" not in name and not PurePosixPath(name).is_absolute(), "UNSAFE_ARCHIVE_MEMBER")
    parts = PurePosixPath(name).parts
    require(parts and ".." not in parts and all(not p.startswith(".") or p == ".gitattributes" for p in parts), "PRIVATE_ARCHIVE_MEMBER")


def write_archive(path, files):
    require(not Path(path).exists(), "ARCHIVE_ALREADY_EXISTS")
    for name in files:
        safe_member(name)
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 26, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)


def package(root, framework, wheel, output):
    root, framework, wheel, output = map(Path, (root, framework, wheel, output))
    result = check(root)
    catalog = load(root / CATALOG)
    manifest = load(root / "docs/integration/p2_handoff_manifest.json")
    wheel_record = load(root / "docs/verification/local_v2_wheel.json")
    require(wheel.name == wheel_record["wheel_filename"] and sha(wheel) == wheel_record["wheel_sha256"], "FIXED_WHEEL_MISMATCH")
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            safe_member(name)
            require(not any(part in name.lower() for part in (".env", ".sqlite", "__pycache__")), "PRIVATE_WHEEL_MEMBER")
        for relative, expected in manifest["runtime_source_hashes"].items():
            require(hashlib.sha256(archive.read(relative)).hexdigest() == expected, "WHEEL_RUNTIME_SOURCE_MISMATCH")
    revision = manifest["framework"]["revision"]
    tree = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", revision, "--", "reliable_codegen", "contracts", "pyproject.toml"], cwd=framework, text=True).splitlines()
    selected = [name for name in tree if name.startswith("reliable_codegen/") and name.endswith(".py")
                or name in {"contracts/openapi_v0.2.json", "contracts/examples_v0.2.json", "pyproject.toml"}]
    require(selected and "contracts/openapi_v0.2.json" in selected, "FRAMEWORK_SNAPSHOT_MISSING")
    files = {"b/" + relative: safe_file(root, relative).read_bytes() for relative in catalog["files"]}
    files["b/" + CATALOG] = (root / CATALOG).read_bytes()
    for name in selected:
        files["framework/" + name] = subprocess.check_output(["git", "show", revision + ":" + name], cwd=framework)
    files["wheels/" + wheel.name] = wheel.read_bytes()
    instructions = """P2 local technical candidate; formal O receipt pending.

Use Python >=3.11 with b/python_service/requirements-local-v2.lock dependencies.
Install the pinned B wheel without resolving dependencies into an isolated target:
  python -m pip install --no-deps --no-index --no-compile --target installed_b wheels/srp_b_local-0.3.1-py3-none-any.whl
Run the Git-free, no-Docker receiver smoke:
  python -I b/python_service/scripts/smoke_p2_consumer.py --bundle-root .
The smoke imports B from installed_b and the fixed framework snapshot.
It performs source/evidence checks plus real AST/rules only. Historical Docker
results are records, not rerun by this smoke. Existing venv dependencies may be
reused, and must not be described as a fresh dependency installation or O receipt.
Full historical driver reproduction requires a fixed Git checkout for its Git
version notes, the exact Docker image, and the reviewed P2 tool snapshot.
Only allowlisted public evidence and fixed dependency sources are packaged.
Raw .interop journals, hidden test originals, private files and credentials stay local.
"""
    files["RECEIVER.txt"] = instructions.encode("utf-8")
    inventory = {name: hashlib.sha256(value).hexdigest() for name, value in sorted(files.items())}
    receipt = {"record_version": "1.0", "runtime_revision": manifest["source"]["revision"], "framework_revision": revision,
               "snapshot_sha256": result["snapshot_sha256"], "files": inventory, "formal_acceptance": "blocked"}
    files["DELIVERY.json"] = (json.dumps(receipt, indent=2) + "\n").encode("utf-8")
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "b-p2-0.3.1-candidate.zip"
    write_archive(destination, files)
    return {"result": "passed", "archive_filename": destination.name, "archive_sha256": sha(destination),
            "archive_entries": len(files), "snapshot_sha256": result["snapshot_sha256"],
            "framework_snapshot_files": len(selected), "wheel_sha256": wheel_record["wheel_sha256"], "formal_p2_acceptance": "blocked"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--framework-root", type=Path, required=True)
    parser.add_argument("--runtime-wheel", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.root, args.framework_root, args.runtime_wheel, args.output_dir)))


if __name__ == "__main__":
    main()

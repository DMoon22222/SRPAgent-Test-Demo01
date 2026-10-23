"""Private durable replay journal. Pending work is never executed a second time."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from reliable_codegen.contracts import ContractError
from reliable_codegen.utils import canonical, digest


class StateConflict(ContractError):
    pass


class Journal:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "calls.sqlite3"
        with self.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS calls (
                operation TEXT, message_id TEXT, request_hash TEXT NOT NULL,
                call_id TEXT UNIQUE NOT NULL, response TEXT,
                PRIMARY KEY(operation, message_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS facts (
                id TEXT PRIMARY KEY, kind TEXT, visibility TEXT, body TEXT, sha256 TEXT)""")
            db.execute("""CREATE TABLE IF NOT EXISTS versions (
                task TEXT, artifact TEXT, revision TEXT, sha256 TEXT,
                PRIMARY KEY(task, artifact, revision))""")
            db.execute("""CREATE TABLE IF NOT EXISTS fixed_tests (
                run TEXT, kind TEXT, artifact TEXT, sha256 TEXT,
                PRIMARY KEY(run, kind))""")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def begin(self, operation, request):
        fingerprint = digest(canonical(request))
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT request_hash,response FROM calls WHERE operation=? AND message_id=?",
                (operation, request["message_id"]),
            ).fetchone()
            if previous:
                if previous[0] != fingerprint:
                    raise StateConflict("IDEMPOTENCY_CONFLICT")
                return "completed" if previous[1] else "pending", json.loads(previous[1]) if previous[1] else None
            if db.execute("SELECT 1 FROM calls WHERE call_id=?", (request["call_id"],)).fetchone():
                raise StateConflict("CALL_GRANT_REUSED")
            db.execute("INSERT INTO calls VALUES (?,?,?,?,NULL)",
                       (operation, request["message_id"], fingerprint, request["call_id"]))
        return "new", None

    def finish(self, operation, request, response):
        with self.connection() as db:
            db.execute("UPDATE calls SET response=? WHERE operation=? AND message_id=?",
                       (canonical(response), operation, request["message_id"]))

    def freeze(self, request):
        payload = request["payload"]
        code, tests = payload["code_artifact"], payload.get("test_artifact")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            key = (request["task_id"], code["artifact_id"], code["revision"])
            row = db.execute("SELECT sha256 FROM versions WHERE task=? AND artifact=? AND revision=?", key).fetchone()
            if row and row[0] != code["content_hash"]:
                raise StateConflict("CODE_REVISION_REUSED")
            db.execute("INSERT OR IGNORE INTO versions VALUES (?,?,?,?)", (*key, code["content_hash"]))
            if tests:
                key = (request["run_id"], tests["kind"])
                identity = (tests["artifact_id"], tests["test_hash"])
                row = db.execute("SELECT artifact,sha256 FROM fixed_tests WHERE run=? AND kind=?", key).fetchone()
                if row and tuple(row) != identity:
                    raise StateConflict("FIXED_TESTS_CHANGED")
                db.execute("INSERT OR IGNORE INTO fixed_tests VALUES (?,?,?,?)", (*key, *identity))

    def save(self, value, kind, identity, visibility="public"):
        body = canonical(value)
        fingerprint = digest(body)
        with self.connection() as db:
            row = db.execute("SELECT kind,visibility,body,sha256 FROM facts WHERE id=?", (identity,)).fetchone()
            record = (kind, visibility, body, fingerprint)
            if row and tuple(row) != record:
                raise StateConflict("FACT_ID_CONFLICT")
            db.execute("INSERT OR IGNORE INTO facts VALUES (?,?,?,?,?)", (identity, *record))
        # These facts have the same canonical representation used by O's store.
        # O already owns any failure source supplied to feedback-only diagnosis.
        return {"artifact_id": identity, "artifact_type": kind, "sha256": fingerprint,
                "media_type": "application/json", "visibility": visibility, "resolver_key": "local-store"}

    def resolve(self, reference, *, allow_restricted=False):
        with self.connection() as db:
            row = db.execute("SELECT kind,visibility,body,sha256 FROM facts WHERE id=?",
                             (reference["artifact_id"],)).fetchone()
        if not row or row[0] != reference["artifact_type"] or row[1] != reference["visibility"]:
            raise ContractError("FACT_NOT_AVAILABLE")
        if row[1] == "restricted" and not allow_restricted:
            raise ContractError("PROTECTED_FACT")
        if row[3] != reference["sha256"] or digest(row[2]) != row[3] or reference["resolver_key"] != "local-store":
            raise ContractError("FACT_HASH_MISMATCH")
        return {"artifact_ref": dict(reference), "body_utf8": row[2], "content_kind": "json"}

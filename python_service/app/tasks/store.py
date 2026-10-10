from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from a2a.types import a2a_pb2 as pb

from app.services.diagnosis_service import ServiceError


class TaskStore:
    """Single-process SQLite store. A file lock prevents unsafe second workers."""
    def __init__(self, path):
        self.path = Path(path)
        self.lock_file = None

    def open(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_file = self.path.with_suffix(".lock").open("a+b")
        self.lock_file.seek(0)
        if os.name == "nt":
            import msvcrt
            if self.lock_file.read(1) == b"":
                self.lock_file.write(b"0")
                self.lock_file.flush()
            self.lock_file.seek(0)
            try:
                msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                self.lock_file.close()
                self.lock_file = None
                raise RuntimeError("A2A store is already owned by another process; use one Uvicorn worker") from None
        else:
            import fcntl
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with self.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, context_id TEXT NOT NULL,
                state INTEGER NOT NULL, updated REAL NOT NULL,
                task BLOB NOT NULL, request TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS tasks_owner_updated ON tasks(owner, updated DESC)")
            db.execute("""CREATE TABLE IF NOT EXISTS code_versions (
                owner TEXT, workflow TEXT, artifact TEXT, revision TEXT, digest TEXT,
                PRIMARY KEY(owner,workflow,artifact,revision))""")
            db.execute("""CREATE TABLE IF NOT EXISTS workflow_tests (
                owner TEXT, workflow TEXT, suite TEXT, revision TEXT, digest TEXT,
                PRIMARY KEY(owner,workflow))""")
            db.execute("""CREATE TABLE IF NOT EXISTS reports (
                owner TEXT, report TEXT, workflow TEXT, PRIMARY KEY(owner,report))""")

    def close(self):
        if self.lock_file:
            self.lock_file.close()
            self.lock_file = None

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def insert(self, task, owner, request_json):
        with self.connection() as db:
            db.execute("INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?)", (
                task.id, owner, task.context_id, task.status.state, time.time(), task.SerializeToString(), request_json))

    def save(self, task, request_json=None):
        with self.connection() as db:
            db.execute("UPDATE tasks SET state=?, updated=?, task=?, request=COALESCE(?,request) WHERE id=?", (
                task.status.state, time.time(), task.SerializeToString(), request_json, task.id))

    def get(self, task_id, owner):
        with self.connection() as db:
            row = db.execute("SELECT task,request FROM tasks WHERE id=? AND owner=?", (task_id, owner)).fetchone()
        return (pb.Task.FromString(row[0]), row[1]) if row else None

    def context_request(self, context_id, owner):
        with self.connection() as db:
            row = db.execute("SELECT request FROM tasks WHERE context_id=? AND owner=? LIMIT 1", (context_id, owner)).fetchone()
        return row[0] if row else None

    def list(self, owner, *, context_id="", state=0, after=None, limit=50, offset=0):
        clauses, args = ["owner=?"], [owner]
        for condition, value in (("context_id=?", context_id), ("state=?", state), ("updated>?", after)):
            if value is not None and value != "" and value != 0:
                clauses.append(condition)
                args.append(value)
        query = " FROM tasks WHERE " + " AND ".join(clauses)
        with self.connection() as db:
            total = db.execute("SELECT COUNT(*)" + query, args).fetchone()[0]
            rows = db.execute("SELECT task" + query + " ORDER BY updated DESC,id DESC LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
        return [pb.Task.FromString(r[0]) for r in rows], total

    def interrupted(self):
        with self.connection() as db:
            rows = db.execute("SELECT task FROM tasks WHERE state IN (?,?)", (pb.TASK_STATE_SUBMITTED, pb.TASK_STATE_WORKING)).fetchall()
        return [pb.Task.FromString(row[0]) for row in rows]

    def register_contract(self, request, owner):
        workflow = request.workflow.workflowId
        with self.connection() as db:
            # Serialize competing revision registrations before checking invariants.
            db.execute("BEGIN IMMEDIATE")
            if request.workflow.previousReportId:
                row = db.execute("SELECT workflow FROM reports WHERE owner=? AND report=?",
                                 (owner, request.workflow.previousReportId)).fetchone()
                if not row or row[0] != workflow:
                    raise ServiceError("REPORT_REFERENCE_CONFLICT", "previousReportId is unknown or belongs to another workflow")
            key = (owner, workflow, request.code.artifactId, request.code.revision)
            digest = request.code.digest()
            row = db.execute("SELECT digest FROM code_versions WHERE owner=? AND workflow=? AND artifact=? AND revision=?", key).fetchone()
            if row and row[0] != digest:
                raise ServiceError("CODE_REVISION_REUSED", "Changed source must use a new code revision")
            db.execute("INSERT OR IGNORE INTO code_versions VALUES (?,?,?,?,?)", (*key, digest))
            if request.tests:
                suite = (request.tests.suiteId, request.tests.revision, request.tests.digest())
                row = db.execute("SELECT suite,revision,digest FROM workflow_tests WHERE owner=? AND workflow=?", (owner, workflow)).fetchone()
                if row and tuple(row) != suite:
                    raise ServiceError("TEST_SUITE_CHANGED", "Repair iterations must retain the original test suite; use a new workflow for a new suite")
                db.execute("INSERT OR IGNORE INTO workflow_tests VALUES (?,?,?,?,?)", (owner, workflow, *suite))

    def register_report(self, result, owner):
        if result.diagnosis:
            with self.connection() as db:
                db.execute("INSERT INTO reports VALUES (?,?,?)", (owner, result.diagnosis.reportId, result.workflow.workflowId))

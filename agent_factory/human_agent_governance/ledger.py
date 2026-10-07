"""Transactional state and keyed audit chain. The host owns the database and key."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from .policy import GovernanceError, canonical


class Ledger:
    def __init__(self, path: Path, key: bytes):
        if len(key) < 32:
            raise GovernanceError("A host-held key of at least 32 bytes is required")
        self.path, self.key = Path(path), key
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, parent TEXT, root TEXT NOT NULL,
                    tools TEXT NOT NULL, expires REAL NOT NULL, stopped INTEGER NOT NULL,
                    depth INTEGER NOT NULL, used INTEGER NOT NULL, limit_units INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY, task TEXT NOT NULL, name TEXT NOT NULL,
                    digest TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    revision TEXT NOT NULL, status TEXT NOT NULL,
                    approval_until REAL, output_digest TEXT);
                CREATE INDEX IF NOT EXISTS operations_fingerprint ON operations(fingerprint);
                CREATE TABLE IF NOT EXISTS audit (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL,
                    previous TEXT NOT NULL, signature TEXT NOT NULL);
            """)
        with self.transaction() as db:
            if db.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 0:
                if (
                    db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] != 0
                    or db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] != 0
                ):
                    raise GovernanceError("Existing state has no audit history")
                self.event(db, "initialized")

    def connect(self) -> sqlite3.Connection:
        try:
            db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            return db
        except sqlite3.Error as exc:
            raise GovernanceError("Ledger unavailable; operation held") from exc

    def digest(self, value: str) -> str:
        return hmac.new(self.key, value.encode(), hashlib.sha256).hexdigest()

    def state_digest(self, db: sqlite3.Connection) -> str:
        value = {}
        for table in ("tasks", "operations"):
            value[table] = [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY id")]
        return self.digest(canonical(value))

    def verify(self, db: sqlite3.Connection) -> None:
        previous, last = "0" * 64, None
        for row in db.execute("SELECT * FROM audit ORDER BY seq"):
            signature = self.digest(previous + row["payload"])
            if row["previous"] != previous or not hmac.compare_digest(signature, row["signature"]):
                raise GovernanceError("Audit history cannot be verified")
            previous, last = signature, json.loads(row["payload"])
        if last is not None and not hmac.compare_digest(last["state"], self.state_digest(db)):
            raise GovernanceError("Ledger state was altered outside the governed transaction")

    def event(self, db: sqlite3.Connection, event: str, **fields: object) -> None:
        previous = db.execute("SELECT signature FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        previous = previous[0] if previous else "0" * 64
        payload = canonical({"event": event, **fields, "state": self.state_digest(db)})
        db.execute(
            "INSERT INTO audit(payload,previous,signature) VALUES(?,?,?)",
            (payload, previous, self.digest(previous + payload)),
        )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            self.verify(db)
            yield db
            db.execute("COMMIT")
        except (sqlite3.Error, OSError, ValueError) as exc:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise GovernanceError("Ledger unavailable; operation held") from exc
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

"""Local per-job authorization audit and session-scoped execution receipts.

This records *affirmation*, not legal ownership; the user remains responsible
for rights. Receipts are intentionally invalid after process restart.
"""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .settings import data_dir

if TYPE_CHECKING:
    from .downloader import DownloadJob

SESSION_ID = secrets.token_hex(24)
MODES = frozenset({"interactive", "--yes", "queued"})


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Receipt:
    id: int
    url_sha256: str
    session_id: str
    mode: str


class AuthorizationDB:
    def __init__(self, path: Path | None = None):
        self.path = path or (data_dir() / "history.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS job_authorizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                queue_item_id INTEGER,
                url_sha256 TEXT NOT NULL,
                mode TEXT NOT NULL,
                session_id TEXT NOT NULL,
                confirmed_at TEXT NOT NULL
            )""")
            con.execute("CREATE INDEX IF NOT EXISTS idx_job_auth_queue ON job_authorizations(queue_item_id,id)")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path, timeout=30)
        try:
            con.execute("PRAGMA busy_timeout=30000")
            with con:
                yield con
        finally:
            con.close()

    def record(self, job: DownloadJob, mode: str, queue_id: int | None = None) -> Receipt:
        if mode not in MODES:
            raise ValueError("Invalid authorization mode")
        hashed = url_hash(job.url)
        with self._connect() as con:
            cur = con.execute(
                "INSERT INTO job_authorizations(queue_item_id,url_sha256,mode,session_id,confirmed_at) "
                "VALUES (?,?,?,?,?)",
                (queue_id, hashed, mode, SESSION_ID,
                 datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
            return Receipt(int(cur.lastrowid), hashed, SESSION_ID, mode)

    def verify(self, job: DownloadJob, receipt: Receipt, queue_id: int | None = None) -> bool:
        if not isinstance(receipt, Receipt) or receipt.session_id != SESSION_ID:
            return False
        if receipt.url_sha256 != url_hash(job.url):
            return False
        with self._connect() as con:
            row = con.execute("SELECT url_sha256,session_id,mode,queue_item_id "
                              "FROM job_authorizations WHERE id=?", (receipt.id,)).fetchone()
        return bool(row and row[0] == receipt.url_sha256 and row[1] == SESSION_ID and
                    row[2] == receipt.mode and (queue_id is None or row[3] == queue_id))

    def link_queue(self, receipt: Receipt, job: DownloadJob, queue_id: int) -> None:
        if not self.verify(job, receipt):
            raise PermissionError("Invalid authorization receipt")
        with self._connect() as con:
            result = con.execute("UPDATE job_authorizations SET queue_item_id=? WHERE id=? "
                                 "AND queue_item_id IS NULL", (queue_id, receipt.id))
            if result.rowcount != 1:
                raise PermissionError("Authorization was previously used for another queue item")

    def current_queue_receipt(self, job: DownloadJob, queue_id: int) -> Receipt | None:
        with self._connect() as con:
            row = con.execute("SELECT id,url_sha256,session_id,mode FROM job_authorizations "
                              "WHERE queue_item_id=? ORDER BY id DESC LIMIT 1", (queue_id,)).fetchone()
        if not row:
            return None
        receipt = Receipt(*row)
        return receipt if self.verify(job, receipt, queue_id) else None

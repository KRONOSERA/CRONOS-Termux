"""Durable FIFO download queue. SQLite lives alongside v1.0 history; no migration of media.

Queued requests store public YouTube URLs in a private local database, not logs.
"""
from __future__ import annotations

import hashlib
import os
import json
import sqlite3
import time
from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path

from .downloader import DownloadJob, DownloadResult, redacted
from .authorization import AuthorizationDB, Receipt, SESSION_ID, url_hash
from .history import HistoryDB
from .settings import data_dir


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fingerprint(job: DownloadJob) -> str:
    value = json.dumps(asdict(job), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class QueuedItem:
    id: int
    job: DownloadJob
    status: str
    attempts: int
    last_error: str = ""
    last_file: str = ""
    priority: int = 0


class QueueDB:
    STATES = frozenset({"queued", "paused", "running", "done", "failed"})
    SCHEMA_VERSION = 3
    LEASE_SECONDS = 120

    @staticmethod
    def _boot_id() -> str | None:
        try:
            value = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
            return value or None
        except (OSError, UnicodeError):
            return None

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (data_dir() / "history.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.auth = AuthorizationDB(self.path)
        with self._connect() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS queue_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_json TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                owner_pid INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_error TEXT NOT NULL DEFAULT '',
                last_file TEXT NOT NULL DEFAULT '',
                priority INTEGER NOT NULL DEFAULT 0
            )""")
            con.execute("CREATE INDEX IF NOT EXISTS idx_queue_status_id ON queue_items(status,id)")
            con.execute("CREATE TABLE IF NOT EXISTS schema_versions (component TEXT PRIMARY KEY, version INTEGER NOT NULL)")
            row = con.execute("SELECT version FROM schema_versions WHERE component='queue'").fetchone()
            if row is not None and row[0] > self.SCHEMA_VERSION:
                raise ValueError("Queue database uses a newer unsupported schema")
            columns = {row[1] for row in con.execute("PRAGMA table_info(queue_items)")}
            for column, spec in (
                ("owner_pid", "INTEGER"),
                ("priority", "INTEGER NOT NULL DEFAULT 0"),
                ("owner_boot_id", "TEXT"),
                ("lease_expires_at", "REAL"),
            ):
                if column not in columns:
                    con.execute(f"ALTER TABLE queue_items ADD COLUMN {column} {spec}")
            con.execute("INSERT INTO schema_versions(component,version) VALUES('queue',?) "
                        "ON CONFLICT(component) DO UPDATE SET version=excluded.version", (self.SCHEMA_VERSION,))

            # Recovery (v1.1 and later): previously, a dead owner PID immediately
            # paused its job. Now wait for the lease to expire AND confirm that
            # the PID is not alive on the original boot. A reused PID on a
            # different boot is not considered the original owner. An unreadable
            # boot ID degrades conservatively to a PID check. Legacy rows without
            # leases are considered expired, but still checked against live PIDs.
            for item_id, pid, boot, expiry in con.execute(
                "SELECT id,owner_pid,owner_boot_id,lease_expires_at "
                "FROM queue_items WHERE status='running'"
            ).fetchall():
                current_boot = self._boot_id()
                same_boot = not boot or not current_boot or boot == current_boot
                is_alive_owner = same_boot and self._pid_alive(pid)
                if (expiry is None or float(expiry) <= time.time()) and not is_alive_owner:
                    con.execute("""UPDATE queue_items SET status='paused',owner_pid=NULL,
                        owner_boot_id=NULL,lease_expires_at=NULL,updated_at=?
                        WHERE id=? AND status='running'""", (utc_now(), item_id))
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    @staticmethod
    def _pid_alive(pid: int | None) -> bool:
        if not isinstance(pid, int) or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path, timeout=30)
        try:
            con.execute("PRAGMA busy_timeout=30000")
            con.execute("PRAGMA journal_mode=WAL")
            with con:
                yield con
        finally:
            con.close()

    def add(self, jobs: list[DownloadJob], receipts: list[Receipt] | None = None) -> tuple[list[int], int]:
        """Require current-session affirmative receipts before any new insertion."""
        if (receipts is None or len(receipts) != len(jobs) or
                not all(isinstance(r, Receipt) for r in receipts) or
                len({r.id for r in receipts}) != len(jobs)):
            raise PermissionError("Each queued job requires a current-session authorization receipt")
        if any(not self.auth.verify(job, receipt) for job, receipt in zip(jobs, receipts)):
            raise PermissionError("Refusing to queue an unauthorized job")
        ids: list[int] = []
        duplicates = 0
        with self._connect() as con:
            for job, receipt in zip(jobs, receipts):
                fp = fingerprint(job)
                existing = con.execute("""SELECT 1 FROM queue_items
                    WHERE fingerprint=? AND status IN ('queued','paused','running') LIMIT 1""", (fp,)).fetchone()
                if existing:
                    duplicates += 1
                    continue
                now = utc_now()
                cur = con.execute("""INSERT INTO queue_items
                    (job_json,fingerprint,status,created_at,updated_at)
                    VALUES (?,?,'queued',?,?)""", (
                        json.dumps(asdict(job), ensure_ascii=False), fp, now, now,
                    ))
                queue_id = int(cur.lastrowid)
                linked = con.execute("""UPDATE job_authorizations SET queue_item_id=?
                    WHERE id=? AND queue_item_id IS NULL AND url_sha256=? AND session_id=?""",
                    (queue_id, receipt.id, url_hash(job.url), SESSION_ID))
                if linked.rowcount != 1:
                    raise PermissionError("Authorization receipt was already consumed")
                ids.append(queue_id)
        return ids, duplicates

    @staticmethod
    def _row(row: sqlite3.Row) -> QueuedItem:
        raw = json.loads(row["job_json"])
        if not isinstance(raw, dict):
            raise ValueError("Invalid stored download job")
        allowed = {f.name for f in fields(DownloadJob)}
        job = DownloadJob(**{k: v for k, v in raw.items() if k in allowed})
        return QueuedItem(row["id"], job, row["status"], row["attempts"],
                          row["last_error"], row["last_file"], row["priority"])

    def list(self, statuses: tuple[str, ...] | None = None, limit: int = 500) -> list[QueuedItem]:
        limit = max(1, min(limit, 2000))
        with self._connect() as con:
            con.row_factory = sqlite3.Row
            if statuses:
                if not set(statuses).issubset(self.STATES):
                    raise ValueError("Unrecognized queue state")
                marks = ",".join("?" for _ in statuses)
                rows = con.execute(f"SELECT * FROM queue_items WHERE status IN ({marks}) ORDER BY priority DESC,id ASC LIMIT ?",
                                   (*statuses, limit)).fetchall()
            else:
                rows = con.execute("SELECT * FROM queue_items ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [self._row(row) for row in rows]

    def counts(self) -> dict[str, int]:
        with self._connect() as con:
            rows = con.execute("SELECT status, COUNT(*) FROM queue_items GROUP BY status").fetchall()
        return {state: dict(rows).get(state, 0) for state in sorted(self.STATES)}

    def start(self, item_id: int, receipt: Receipt | None = None) -> bool:
        items = [item for item in self.list(statuses=("queued",), limit=2000) if item.id == item_id]
        if not items or receipt is None or not self.auth.verify(items[0].job, receipt, item_id):
            return False
        with self._connect() as con:
            result = con.execute("""UPDATE queue_items SET status='running', attempts=attempts+1,
                owner_pid=?,owner_boot_id=?,lease_expires_at=?,updated_at=?
                WHERE id=? AND status='queued'""",
                (os.getpid(), self._boot_id(), time.time() + self.LEASE_SECONDS, utc_now(), item_id))
            return result.rowcount == 1

    def renew(self, item_id: int) -> bool:
        """Extend a lease held by this process; never steal another process's job."""
        with self._connect() as con:
            result = con.execute("""UPDATE queue_items SET lease_expires_at=?,updated_at=?
                WHERE id=? AND status='running' AND owner_pid=? AND
                (owner_boot_id=? OR (owner_boot_id IS NULL AND ? IS NULL))""",
                (time.time() + self.LEASE_SECONDS, utc_now(), item_id,
                 os.getpid(), self._boot_id(), self._boot_id()))
            return result.rowcount == 1

    def finish(self, item_id: int, result: DownloadResult) -> bool:
        target = {"success": "done", "skipped": "done", "cancelled": "paused", "failed": "failed"}.get(result.status)
        if target is None:
            raise ValueError("Unknown download result")
        with self._connect() as con:
            cursor = con.execute("""UPDATE queue_items SET status=?,last_error=?,last_file=?,
                owner_pid=NULL,owner_boot_id=NULL,lease_expires_at=NULL,updated_at=?
                WHERE id=? AND status IN ('running','queued')""", (
                    target, redacted(result.reason), result.file, utc_now(), item_id,
                ))
            return cursor.rowcount == 1

    def change(self, item_id: int, status: str) -> bool:
        targets = {"paused": ("queued", "failed"), "queued": ("paused", "failed")}
        if status not in targets:
            raise ValueError("Only queued and paused transitions are supported")
        origin = targets[status]
        with self._connect() as con:
            cur = con.execute("""UPDATE queue_items SET status=?,updated_at=?
                WHERE id=? AND status IN (?,?)""", (status, utc_now(), item_id, *origin))
            return cur.rowcount == 1

    def change_all(self, status: str) -> int:
        """Bulk pause waiting jobs or requeue interrupted/failed jobs; never touch running jobs."""
        if status == "paused":
            origin = ("queued",)
        elif status == "queued":
            origin = ("paused", "failed")
        else:
            raise ValueError("Unsupported bulk transition")
        placeholders = ",".join("?" for _ in origin)
        with self._connect() as con:
            cur = con.execute(
                f"UPDATE queue_items SET status=?, updated_at=? WHERE status IN ({placeholders})",
                (status, utc_now(), *origin),
            )
            return cur.rowcount

    def prioritize(self, item_id: int, priority: int) -> bool:
        """Set 0..9 priority for pending jobs, without mutating active transfers."""
        if type(priority) is not int or not 0 <= priority <= 9:
            raise ValueError("Priority must be 0..9")
        with self._connect() as con:
            result = con.execute("UPDATE queue_items SET priority=?,updated_at=? "
                                 "WHERE id=? AND status IN ('queued','paused','failed')",
                                 (priority, utc_now(), item_id))
            return result.rowcount == 1

    def remove(self, item_id: int) -> bool:
        with self._connect() as con:
            cur = con.execute("DELETE FROM queue_items WHERE id=? AND status!='running'", (item_id,))
            return cur.rowcount == 1

    def clear_completed(self) -> int:
        with self._connect() as con:
            cur = con.execute("DELETE FROM queue_items WHERE status='done'")
            return cur.rowcount

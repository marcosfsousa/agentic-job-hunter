from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from types import TracebackType

from jobscout.models import FeedbackEntry, JobListing

logger = logging.getLogger(__name__)

_CREATE_SEEN_JOBS = """
CREATE TABLE IF NOT EXISTS seen_jobs (
    id          TEXT NOT NULL,
    source      TEXT NOT NULL,
    first_seen  TEXT NOT NULL,
    title       TEXT,
    company     TEXT,
    description TEXT,
    PRIMARY KEY (id, source)
)
"""

_CREATE_FEEDBACK = """
CREATE TABLE IF NOT EXISTS feedback (
    id          TEXT NOT NULL,
    source      TEXT NOT NULL,
    status      TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (id, source)
)
"""

_CREATE_DIGEST_JOBS = """
CREATE TABLE IF NOT EXISTS digest_jobs (
    id          TEXT NOT NULL,
    source      TEXT NOT NULL,
    digest_date TEXT NOT NULL,
    PRIMARY KEY (id, source, digest_date)
)
"""


def _id_source_params(jobs: list[JobListing]) -> tuple[str, list]:
    """Build SQL placeholders and flat params for (id, source) IN (...) queries."""
    pairs = [(j.id, j.source) for j in jobs]
    placeholders = ",".join("(?,?)" for _ in pairs)
    flat_params = [v for pair in pairs for v in pair]
    return placeholders, flat_params


class JobDatabase:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> JobDatabase:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute(_CREATE_SEEN_JOBS)
        self._conn.execute(_CREATE_FEEDBACK)
        self._conn.execute(_CREATE_DIGEST_JOBS)
        try:
            self._conn.execute("ALTER TABLE seen_jobs ADD COLUMN company TEXT")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc):
                raise
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_seen_jobs_first_seen ON seen_jobs(first_seen)"
        )
        self._conn.commit()
        logger.debug("JobDatabase opened: %s", self._db_path)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            logger.debug("JobDatabase closed: %s", self._db_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def filter_unseen(self, jobs: list[JobListing]) -> list[JobListing]:
        """Return only jobs not yet recorded in seen_jobs."""
        if not jobs:
            return []
        conn = self._require_conn()
        placeholders, flat_params = _id_source_params(jobs)
        rows = conn.execute(
            f"SELECT id, source FROM seen_jobs WHERE (id, source) IN ({placeholders})",
            flat_params,
        ).fetchall()
        seen = set(rows)
        unseen = [j for j in jobs if (j.id, j.source) not in seen]
        logger.debug("filter_unseen: %d → %d unseen jobs", len(jobs), len(unseen))
        return unseen

    def upsert_feedback(self, entries: list[FeedbackEntry]) -> None:
        """Insert or update feedback entries."""
        if not entries:
            return
        conn = self._require_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.executemany(
            "INSERT OR REPLACE INTO feedback (id, source, status, updated_at) VALUES (?, ?, ?, ?)",
            [(e.id, e.source, e.status, now) for e in entries],
        )
        conn.commit()
        logger.debug("upsert_feedback: recorded %d entries", len(entries))

    def filter_feedback(self, jobs: list[JobListing]) -> list[JobListing]:
        """Return jobs not marked applied or rejected in the feedback table."""
        if not jobs:
            return []
        conn = self._require_conn()
        placeholders, flat_params = _id_source_params(jobs)
        rows = conn.execute(
            f"SELECT id, source FROM feedback"
            f" WHERE status IN ('applied', 'rejected')"
            f" AND (id, source) IN ({placeholders})",
            flat_params,
        ).fetchall()
        excluded = set(rows)
        result = [j for j in jobs if (j.id, j.source) not in excluded]
        logger.debug("filter_feedback: %d → %d actionable jobs", len(jobs), len(result))
        return result

    def get_interested_descriptions(self) -> list[str]:
        """Return job texts for all 'interested' feedback entries that have stored text."""
        conn = self._require_conn()
        rows = conn.execute(
            "SELECT s.title, s.description"
            " FROM seen_jobs s"
            " JOIN feedback f ON s.id = f.id AND s.source = f.source"
            " WHERE f.status IN ('interested', 'applied')"
            "   AND s.description IS NOT NULL",
        ).fetchall()
        return [f"{title}. {desc}" for title, desc in rows]

    def get_unreviewed_for_date(self, dt: date) -> list[tuple[str, str, str, str]]:
        """Return (id, source, title, company) for jobs first seen on `dt` with no feedback entry."""
        conn = self._require_conn()
        rows = conn.execute(
            "SELECT id, source, title, company FROM seen_jobs"
            " WHERE DATE(first_seen) = ?"
            " AND (id, source) NOT IN (SELECT id, source FROM feedback)",
            (dt.isoformat(),),
        ).fetchall()
        return [(id_, src, title or "", company or "") for id_, src, title, company in rows]

    def mark_in_digest(self, ids_sources: list[tuple[str, str]], digest_date: date) -> None:
        """Record which jobs appeared in the digest for a given date. Idempotent."""
        if not ids_sources:
            return
        conn = self._require_conn()
        digest_iso = digest_date.isoformat()
        conn.executemany(
            "INSERT OR IGNORE INTO digest_jobs (id, source, digest_date) VALUES (?, ?, ?)",
            [(id_, src, digest_iso) for id_, src in ids_sources],
        )
        conn.commit()
        logger.debug("mark_in_digest: recorded %d jobs for %s", len(ids_sources), digest_date)

    def get_unreviewed_for_digest(self, dt: date) -> list[tuple[str, str, str, str]]:
        """Return (id, source, title, company) for digest jobs on `dt` with no feedback."""
        conn = self._require_conn()
        rows = conn.execute(
            "SELECT s.id, s.source, s.title, s.company"
            " FROM seen_jobs s"
            " JOIN digest_jobs d ON s.id = d.id AND s.source = d.source"
            " WHERE d.digest_date = ?"
            " AND (s.id, s.source) NOT IN (SELECT id, source FROM feedback)",
            (dt.isoformat(),),
        ).fetchall()
        return [(id_, src, title or "", company or "") for id_, src, title, company in rows]

    def mark_seen_bulk(self, jobs: list[JobListing]) -> None:
        """Record jobs as seen with their text. Safe to call multiple times on the same jobs."""
        if not jobs:
            return
        conn = self._require_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.executemany(
            "INSERT OR IGNORE INTO seen_jobs (id, source, first_seen, title, company, description)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [(j.id, j.source, now, j.title, j.company, j.description) for j in jobs],
        )
        conn.commit()
        logger.debug("mark_seen_bulk: recorded %d jobs", len(jobs))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("JobDatabase must be used as a context manager")
        return self._conn

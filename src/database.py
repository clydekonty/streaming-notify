"""SQLite database persistence and deduplication for streaming alerts."""

from contextlib import contextmanager
import datetime
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger(__name__)


class AlertDatabase:
    """Manages alert records and ensures deduplication via SQLite."""

    def __init__(self, db_path: Path | str = "alerts.db"):
        self.db_path = Path(db_path)
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Create a connection with row factory enabled and ensure proper closure."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        """Initialize SQLite table schema if it does not exist."""
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alerts (
                    tmdb_id INTEGER,
                    service TEXT,
                    title TEXT,
                    notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (tmdb_id, service)
                )
                """
            )
            conn.commit()
        logger.debug("Database initialized at %s", self.db_path)

    def is_notified(self, tmdb_id: int, service: str) -> bool:
        """Check if an alert has already been sent for this (tmdb_id, service) pair."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM alerts WHERE tmdb_id = ? AND service = ?",
                (tmdb_id, service),
            )
            return cursor.fetchone() is not None

    def record_notification(
        self,
        tmdb_id: int,
        service: str,
        title: str,
        notified_at: Optional[str] = None,
    ):
        """Record that an alert has been delivered."""
        now = notified_at or datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO alerts (tmdb_id, service, title, notified_at)
                VALUES (?, ?, ?, ?)
                """,
                (tmdb_id, service, title, now),
            )
            conn.commit()
        logger.debug("Recorded alert: tmdb_id=%d, service='%s', title='%s'", tmdb_id, service, title)

    def record_batch(self, alerts: List[Dict[str, Any]]):
        """Record multiple notifications in a single transaction."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO alerts (tmdb_id, service, title, notified_at)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (a["tmdb_id"], a["service"], a["title"], a.get("notified_at") or now)
                    for a in alerts
                ],
            )
            conn.commit()
        logger.info("Recorded %d new alerts in database.", len(alerts))

    def get_all_alerts(self) -> List[Dict[str, Any]]:
        """Retrieve all recorded alerts from the database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT tmdb_id, service, title, notified_at FROM alerts ORDER BY notified_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    def get_alert_count(self) -> int:
        """Return total number of recorded alerts."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM alerts")
            return cursor.fetchone()[0]

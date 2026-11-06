"""SQLite database persistence and deduplication for streaming alerts.

Maintains both a local SQLite database (for local runs) and a git-friendly,
privacy-preserving state file (state/alerts_state.json) so GitHub Actions can
persist alert state across runs without exposing subscriptions or requiring manual pushes.
"""

from contextlib import contextmanager
import datetime
import hashlib
import hmac
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, Generator, List, Optional, Set

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = Path(__file__).resolve().parent.parent / "state" / "alerts_state.json"


class AlertDatabase:
    """Manages alert records and ensures deduplication via SQLite and state/alerts_state.json."""

    def __init__(
        self,
        db_path: Path | str = "alerts.db",
        state_path: Optional[Path | str] = None,
        secret_key: Optional[str] = None,
    ):
        self.db_path = Path(db_path)
        self.state_path = Path(state_path) if state_path else Path(DEFAULT_STATE_PATH)
        self.secret_key = secret_key or "letterboxd-streaming-notify-salt"
        self.notified_hashes: Set[str] = set()

        self._init_db()
        self._load_state_file()
        self._sync_sqlite_and_state()

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

    def _compute_hash(self, tmdb_id: int, service: str) -> str:
        """Compute a privacy-safe HMAC hash of (tmdb_id, service)."""
        norm = f"{tmdb_id}:{service.lower().strip()}"
        key_bytes = self.secret_key.encode("utf-8")
        return hmac.new(key_bytes, norm.encode("utf-8"), hashlib.sha256).hexdigest()

    def _load_state_file(self):
        """Load notified hashes from state/alerts_state.json if it exists."""
        if self.state_path.is_file():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                hashes = data.get("notified_hashes", [])
                self.notified_hashes.update(hashes)
                logger.info(
                    "Loaded %d previously notified alert hashes from %s",
                    len(hashes),
                    self.state_path,
                )
            except Exception as e:
                logger.warning("Failed to load state file %s: %s", self.state_path, e)

    def _save_state_file(self):
        """Save the updated list of notified hashes to state/alerts_state.json."""
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": 1,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "notified_hashes": sorted(list(self.notified_hashes)),
            }
            self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            logger.debug(
                "Saved %d state hashes to %s",
                len(self.notified_hashes),
                self.state_path,
            )
        except Exception as e:
            logger.warning("Failed to save state file %s: %s", self.state_path, e)

    def _sync_sqlite_and_state(self):
        """Synchronize between SQLite and state/alerts_state.json."""
        # 1. Read existing records from SQLite and ensure their hashes are in notified_hashes
        initial_hash_count = len(self.notified_hashes)
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT tmdb_id, service FROM alerts")
                for row in cursor.fetchall():
                    h = self._compute_hash(row["tmdb_id"], row["service"])
                    self.notified_hashes.add(h)
        except Exception as e:
            logger.debug("Could not read SQLite for sync: %s", e)

        # 2. If new hashes were found from SQLite, update state file
        if len(self.notified_hashes) > initial_hash_count or not self.state_path.is_file():
            self._save_state_file()

    def is_notified(self, tmdb_id: int, service: str) -> bool:
        """
        Check if an alert has already been sent for this (tmdb_id, service) pair.
        Checks both the local SQLite database and the persistent state file.
        """
        h = self._compute_hash(tmdb_id, service)
        if h in self.notified_hashes:
            return True

        # Check SQLite as fallback
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM alerts WHERE tmdb_id = ? AND service = ?",
                (tmdb_id, service),
            )
            if cursor.fetchone() is not None:
                self.notified_hashes.add(h)
                return True

        return False

    def record_notification(
        self,
        tmdb_id: int,
        service: str,
        title: str,
        notified_at: Optional[str] = None,
    ):
        """Record that an alert has been delivered in both SQLite and state file."""
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

        # Update persistent state
        h = self._compute_hash(tmdb_id, service)
        self.notified_hashes.add(h)
        self._save_state_file()
        logger.debug("Recorded alert: tmdb_id=%d, service='%s', title='%s'", tmdb_id, service, title)

    def record_batch(self, alerts: List[Dict[str, Any]]):
        """Record multiple notifications in a single transaction in SQLite and state file."""
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

        # Update persistent state
        for a in alerts:
            h = self._compute_hash(a["tmdb_id"], a["service"])
            self.notified_hashes.add(h)
        self._save_state_file()
        logger.info("Recorded %d new alerts in database and state file.", len(alerts))

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
            return max(cursor.fetchone()[0], len(self.notified_hashes))

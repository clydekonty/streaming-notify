"""Test suite for the Letterboxd Streaming Alert pipeline."""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import feedparser

from src.config import Config, load_email_from_file, load_streaming_services
from src.database import AlertDatabase
from src.matcher import find_matched_services, match_service, normalize_service_name
from src.notifier import AlertItem, generate_email_content
from src.tmdb import TMDBAvailability, TMDBClient, TMDBProvider
from src.watchlist import WatchlistFilm, parse_film_from_entry


class TestPipeline(unittest.TestCase):
    """Unit and mock integration tests for the streaming alert pipeline."""

    def test_config_loader(self):
        """Verify configuration loading and privacy separation."""
        services = load_streaming_services()
        self.assertIsInstance(services, list)
        self.assertGreater(len(services), 0)
        self.assertIn("Netflix", services)
        self.assertIn("Criterion Channel", services)

        cfg = Config()
        self.assertTrue(len(cfg.target_services) >= 9)

        # Test validation
        issues_dry = cfg.validate_for_run(dry_run=True)
        self.assertIsInstance(issues_dry, list)

    def test_feed_parsing(self):
        """Verify feedparser correctly extracts film titles and years."""
        sample_rss = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0" xmlns:letterboxd="https://letterboxd.com" xmlns:tmdb="https://themoviedb.org">
          <channel>
            <title>Letterboxd - kclyde Watchlist</title>
            <item>
              <title>Vice, 2018 - ★★★★</title>
              <link>https://letterboxd.com/film/vice-2018/</link>
              <letterboxd:filmTitle>Vice</letterboxd:filmTitle>
              <letterboxd:filmYear>2018</letterboxd:filmYear>
              <tmdb:movieId>429197</tmdb:movieId>
            </item>
            <item>
              <title>Dazed and Confused (1993)</title>
              <link>https://letterboxd.com/film/dazed-and-confused/</link>
            </item>
          </channel>
        </rss>"""

        feed = feedparser.parse(sample_rss)
        self.assertEqual(len(feed.entries), 2)

        # Item 1 with explicit letterboxd tags and tmdb id
        film1 = parse_film_from_entry(feed.entries[0])
        self.assertIsNotNone(film1)
        self.assertEqual(film1.title, "Vice")
        self.assertEqual(film1.year, 2018)
        self.assertEqual(film1.tmdb_id, 429197)

        # Item 2 with title parsing
        film2 = parse_film_from_entry(feed.entries[1])
        self.assertIsNotNone(film2)
        self.assertEqual(film2.title, "Dazed and Confused")
        self.assertEqual(film2.year, 1993)

    def test_provider_name_matching(self):
        """Verify normalization and fuzzy provider matching."""
        # Exact and minor variations
        self.assertTrue(match_service("Disney Plus", "Disney+"))
        self.assertTrue(match_service("Apple TV Plus", "Apple TV+"))
        self.assertTrue(match_service("Apple TV Plus", "Apple TV"))
        self.assertTrue(match_service("Criterion Channel", "The Criterion Channel"))
        self.assertTrue(match_service("Amazon Prime Video", "Prime Video"))
        self.assertTrue(match_service("Amazon Prime Video", "Amazon Prime Video with Ads"))
        self.assertTrue(match_service("Paramount Plus", "Paramount+ with Showtime"))
        self.assertTrue(match_service("Peacock", "Peacock Premium"))
        self.assertTrue(match_service("Max", "HBO Max"))
        self.assertTrue(match_service("Max", "Max"))
        self.assertTrue(match_service("Netflix", "Netflix"))
        self.assertTrue(match_service("Hulu", "Hulu"))

        # False positive prevention
        self.assertFalse(match_service("Max", "Cinemax"))
        self.assertFalse(match_service("Hulu", "FuboTV"))
        self.assertFalse(match_service("Criterion Channel", "MUBI"))

    def test_database_persistence_and_deduplication(self):
        """Verify SQLite creation, deduplication, and persistence."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_db:
            db_path = tmp_db.name

        try:
            db = AlertDatabase(db_path)
            self.assertEqual(db.get_alert_count(), 0)

            # Not notified yet
            self.assertFalse(db.is_notified(429197, "Netflix"))

            # Record alert
            db.record_notification(429197, "Netflix", "Vice")
            self.assertTrue(db.is_notified(429197, "Netflix"))
            self.assertEqual(db.get_alert_count(), 1)

            # Same movie on different service should NOT be notified yet
            self.assertFalse(db.is_notified(429197, "Criterion Channel"))

            # Record batch
            db.record_batch([
                {"tmdb_id": 429197, "service": "Criterion Channel", "title": "Vice"},
                {"tmdb_id": 12345, "service": "Max", "title": "Dazed and Confused"},
            ])
            self.assertEqual(db.get_alert_count(), 3)
            self.assertTrue(db.is_notified(429197, "Criterion Channel"))
            self.assertTrue(db.is_notified(12345, "Max"))
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    def test_email_html_generation(self):
        """Verify email generator creates valid HTML with film cards and links."""
        alerts = [
            AlertItem(
                tmdb_id=429197,
                title="Vice",
                year=2018,
                service="Netflix",
                letterboxd_link="https://letterboxd.com/film/vice-2018/",
                tmdb_watch_link="https://www.themoviedb.org/movie/429197-vice/watch",
            )
        ]
        text, html_body = generate_email_content(alerts, username="kclyde")
        self.assertIn("Vice", text)
        self.assertIn("Netflix", text)
        self.assertIn("Vice", html_body)
        self.assertIn("Netflix", html_body)
        self.assertIn("(2018)", html_body)
        self.assertIn("Where to Watch", html_body)
        self.assertIn("letterboxd.com/kclyde/watchlist", html_body)

    @patch("src.tmdb.TMDBClient.check_movie")
    def test_mock_pipeline_run(self, mock_check_movie):
        """Simulate end-to-end pipeline run with mock data."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_db:
            db_path = tmp_db.name

        try:
            db = AlertDatabase(db_path)
            target_services = ["Netflix", "Criterion Channel"]

            # Mock TMDB response
            mock_check_movie.return_value = TMDBAvailability(
                tmdb_id=429197,
                title="Vice",
                year=2018,
                watch_link="https://www.themoviedb.org/movie/429197/watch",
                providers=[
                    TMDBProvider(provider_id=8, provider_name="Netflix"),
                    TMDBProvider(provider_id=257, provider_name="FuboTV"),
                ],
            )

            # Match providers
            avail = mock_check_movie.return_value
            matches = find_matched_services(target_services, avail.providers)
            self.assertEqual(len(matches), 1)
            target_name, provider = matches[0]
            self.assertEqual(target_name, "Netflix")
            self.assertEqual(provider.provider_name, "Netflix")

            # Check database: first time -> new alert
            self.assertFalse(db.is_notified(avail.tmdb_id, target_name))
            db.record_notification(avail.tmdb_id, target_name, avail.title)

            # Check database: second time -> deduplicated
            self.assertTrue(db.is_notified(avail.tmdb_id, target_name))
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)


if __name__ == "__main__":
    unittest.main()


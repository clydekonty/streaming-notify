#!/usr/bin/env python3
"""Letterboxd Watchlist Streaming Alert Pipeline.

Checks a Letterboxd watchlist against TMDB watch providers for active
streaming subscriptions and delivers email notifications for new arrivals.
"""

import argparse
import logging
import sys
from typing import List

from src.config import config
from src.database import AlertDatabase
from src.matcher import find_matched_services
from src.notifier import AlertItem, EmailNotifier
from src.tmdb import TMDBAvailability, TMDBClient, TMDBProvider
from src.watchlist import fetch_watchlist


def setup_logging(verbose: bool = False):
    """Configure console logging format."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def run_pipeline(
    dry_run: bool = False,
    limit: int = 0,
    db_path: str = None,
    verbose: bool = False,
    mock: bool = False,
) -> int:
    """Execute the full alert pipeline."""
    setup_logging(verbose)
    logger = logging.getLogger("main")

    logger.info("=== Letterboxd Streaming Alert Pipeline Started ===")
    if dry_run:
        logger.info("[MODE] DRY RUN ENABLED - No emails will be sent and DB won't be updated.")
    if mock:
        logger.info("[MODE] MOCK MODE ENABLED - Simulating TMDB streaming responses.")

    # 1. Validate configuration
    if not mock:
        issues = config.validate_for_run(dry_run=dry_run)
        if issues:
            for issue in issues:
                logger.error("Configuration Issue: %s", issue)
            if not dry_run or not config.tmdb_api_key:
                logger.error(
                    "Please configure required credentials in .env or via environment variables."
                )
                return 1

    # Log loaded configuration
    logger.info("Monitoring Letterboxd user: @%s", config.letterboxd_username)
    logger.info("Recipient Email: %s", config.recipient_email)
    logger.info(
        "Active Subscriptions (%d): %s",
        len(config.target_services),
        ", ".join(config.target_services),
    )

    # 2. Initialize Database
    db = AlertDatabase(db_path or config.db_path, secret_key=config.tmdb_api_key)
    total_existing = db.get_alert_count()
    logger.info("Database loaded (%s) with %d existing alert records.", db.db_path, total_existing)

    # 3. Fetch Watchlist
    try:
        films = fetch_watchlist(config.letterboxd_watchlist_url, username=config.letterboxd_username)
    except Exception as e:
        logger.error("Failed to fetch Letterboxd watchlist: %s", e)
        return 1

    if not films:
        logger.warning("No films found in watchlist feed.")
        return 0

    if limit > 0:
        logger.info("Applying limit: checking only first %d of %d films.", limit, len(films))
        films = films[:limit]
    else:
        logger.info("Checking %d films from watchlist...", len(films))

    # 4. TMDB & Streaming Provider Lookups
    tmdb = TMDBClient(api_key=config.tmdb_api_key or "mock_key")
    new_alerts: List[AlertItem] = []

    # Mock provider mappings for demonstration if in mock mode
    mock_db = {
        "Vice": [TMDBProvider(8, "Netflix")],
        "Dazed and Confused": [TMDBProvider(1899, "Max")],
        "Trading Places": [TMDBProvider(9, "Amazon Prime Video")],
        "The Stranger": [TMDBProvider(8, "Netflix")],
        "Brothers": [TMDBProvider(15, "Hulu")],
    }

    for i, film in enumerate(films, 1):
        year_str = f" ({film.year})" if film.year else ""
        logger.debug("[%d/%d] Checking '%s%s'...", i, len(films), film.title, year_str)

        try:
            if mock:
                providers = mock_db.get(film.title, [])
                avail = TMDBAvailability(
                    tmdb_id=1000 + i,
                    title=film.title,
                    year=film.year,
                    watch_link=f"https://www.themoviedb.org/movie/{1000 + i}/watch?locale=US",
                    providers=providers,
                ) if providers else None
            else:
                avail = tmdb.check_movie(
                    title=film.title,
                    year=film.year,
                    region="US",
                    known_tmdb_id=film.tmdb_id,
                )
        except Exception as e:
            logger.warning("Failed lookup for '%s': %s", film.title, e)
            continue

        if not avail:
            logger.debug("  -> Not found on TMDB.")
            continue

        if not avail.providers:
            logger.debug("  -> No US flatrate streaming providers currently available.")
            continue

        # Match available providers against target services
        matches = find_matched_services(config.target_services, avail.providers)
        if not matches:
            available_names = [p.provider_name for p in avail.providers]
            logger.debug("  -> Streaming on %s (not in target subscriptions).", available_names)
            continue

        # Check deduplication in database
        for target_service, provider in matches:
            if db.is_notified(avail.tmdb_id, target_service):
                logger.debug(
                    "  -> Already notified for '%s' on %s.", avail.title, target_service
                )
            else:
                logger.info(
                    "  ★ NEW ARRIVAL: '%s%s' is streaming on %s!",
                    avail.title,
                    f" ({avail.year})" if avail.year else "",
                    target_service,
                )
                new_alerts.append(
                    AlertItem(
                        tmdb_id=avail.tmdb_id,
                        title=avail.title,
                        year=avail.year,
                        service=target_service,
                        letterboxd_link=film.link,
                        tmdb_watch_link=avail.watch_link,
                        logo_url=provider.logo_path,
                    )
                )

    # 5. Handle Notifications
    if not new_alerts:
        print("\nStatus: No new watchlist titles found streaming on your active subscriptions. Skipping email.")
        logger.info("=== Pipeline Completed (0 new alerts) ===")
        return 0

    print(f"\nStatus: Found {len(new_alerts)} new title(s) available on your streaming subscriptions!")
    for item in new_alerts:
        print(f"  • {item.title} ({item.year or 'N/A'}) -> {item.service}")

    # Send email notification
    notifier = EmailNotifier(
        sender_email=config.sender_email,
        sender_app_password=config.sender_app_password,
        recipient_email=config.recipient_email,
    )

    sent = notifier.send_alert(
        alerts=new_alerts,
        username=config.letterboxd_username,
        dry_run=dry_run,
    )

    # Record in database if sent and not dry-run
    if sent and not dry_run:
        records = [
            {"tmdb_id": a.tmdb_id, "service": a.service, "title": a.title}
            for a in new_alerts
        ]
        db.record_batch(records)
        logger.info("Recorded %d new alerts in database.", len(records))

    logger.info("=== Pipeline Completed Successfully ===")
    return 0


def main():
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Check Letterboxd watchlist against streaming subscriptions and send alerts."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate the run without sending emails or updating the database.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run in mock mode simulating TMDB responses (ideal for testing without API keys).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of watchlist films to check (default: all).",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Path to SQLite database file (default: alerts.db).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug-level logging.",
    )

    args = parser.parse_args()
    sys.exit(
        run_pipeline(
            dry_run=args.dry_run,
            mock=args.mock,
            limit=args.limit,
            db_path=args.db,
            verbose=args.verbose,
        )
    )


if __name__ == "__main__":
    main()

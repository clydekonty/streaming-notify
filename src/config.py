"""Configuration and secrets loader for Letterboxd Streaming Alert."""

import logging
import os
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
SECRETS_DIR = BASE_DIR / "secrets"

# Load .env file
load_dotenv(BASE_DIR / ".env")


def load_email_from_file() -> Optional[str]:
    """Check config/email.txt or secrets/email.txt for email address."""
    for path in [CONFIG_DIR / "email.txt", SECRETS_DIR / "email.txt", BASE_DIR / "email.txt"]:
        if path.is_file():
            try:
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    lines = [line.strip() for line in content.splitlines() if line.strip() and not line.strip().startswith("#")]
                    if lines:
                        # If formatted as KEY=VALUE, extract first value or email
                        for line in lines:
                            if "=" in line:
                                key, val = line.split("=", 1)
                                if "email" in key.lower():
                                    return val.strip()
                            elif "@" in line:
                                return line.strip()
                        return lines[0]
            except Exception as e:
                logger.warning("Failed to read email from %s: %s", path, e)
    return None


def load_streaming_services() -> List[str]:
    """Load target streaming services from config/services.txt or env var."""
    # 1. Try config/services.txt or secrets/services.txt
    for path in [CONFIG_DIR / "services.txt", SECRETS_DIR / "services.txt", BASE_DIR / "services.txt"]:
        if path.is_file():
            try:
                content = path.read_text(encoding="utf-8")
                services = [
                    line.strip()
                    for line in content.splitlines()
                    if line.strip() and not line.strip().startswith("#")
                ]
                if services:
                    logger.debug("Loaded %d streaming services from %s", len(services), path)
                    return services
            except Exception as e:
                logger.warning("Failed to read streaming services from %s: %s", path, e)

    # 2. Try environment variable STREAMING_SERVICES
    env_services = os.getenv("STREAMING_SERVICES")
    if env_services:
        # Check if comma or newline separated
        delim = "\n" if "\n" in env_services else ","
        services = [s.strip() for s in env_services.split(delim) if s.strip()]
        if services:
            logger.debug("Loaded %d streaming services from STREAMING_SERVICES env var", len(services))
            return services

    # 3. Fallback to example file if present
    example_path = CONFIG_DIR / "services.example.txt"
    if example_path.is_file():
        try:
            content = example_path.read_text(encoding="utf-8")
            services = [
                line.strip()
                for line in content.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            if services:
                logger.info("Using default streaming services from %s", example_path)
                return services
        except Exception:
            pass

    return []


class Config:
    """Application configuration holder."""

    def __init__(self):
        # TMDB
        self.tmdb_api_key: Optional[str] = os.getenv("TMDB_API_KEY")

        # Emails
        file_email = load_email_from_file()
        self.sender_email: Optional[str] = os.getenv("SENDER_EMAIL") or file_email
        self.recipient_email: Optional[str] = os.getenv("RECIPIENT_EMAIL") or file_email
        self.sender_app_password: Optional[str] = os.getenv("SENDER_APP_PASSWORD")

        # Letterboxd
        self.letterboxd_username: str = os.getenv("LETTERBOXD_USERNAME", "kclyde")
        self.letterboxd_watchlist_url: str = os.getenv(
            "LETTERBOXD_WATCHLIST_URL",
            f"https://letterboxd.com/{self.letterboxd_username}/watchlist/rss/",
        )

        # Database
        self.db_path: Path = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "alerts.db")))

        # Target Streaming Services
        self.target_services: List[str] = load_streaming_services()

    def validate_for_run(self, dry_run: bool = False) -> List[str]:
        """Validate config and return a list of warning/error messages."""
        issues = []
        if not self.tmdb_api_key:
            issues.append(
                "TMDB_API_KEY is not set. Set it in .env or via environment variable to query TMDB."
            )
        if not self.target_services:
            issues.append(
                "No target streaming services found. Please configure config/services.txt or STREAMING_SERVICES."
            )
        if not dry_run:
            if not self.sender_email:
                issues.append("SENDER_EMAIL is not set. Set it in .env or config/email.txt.")
            if not self.recipient_email:
                issues.append("RECIPIENT_EMAIL is not set. Set it in .env or config/email.txt.")
            if not self.sender_app_password:
                issues.append(
                    "SENDER_APP_PASSWORD is not set. An email app password is required to send alerts."
                )
        return issues


# Singleton instance
config = Config()


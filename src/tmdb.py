"""The Movie Database (TMDB) client for movie lookups and watch providers."""

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

TMDB_BASE_URL = "https://api.themoviedb.org/3"


@dataclass
class TMDBProvider:
    """Represents a streaming provider returned by TMDB."""
    provider_id: int
    provider_name: str
    logo_path: Optional[str] = None


@dataclass
class TMDBAvailability:
    """Represents the streaming availability for a movie in a specific region."""
    tmdb_id: int
    title: str
    year: Optional[int]
    watch_link: Optional[str]
    providers: List[TMDBProvider]


class TMDBClient:
    """Client for querying TMDB API v3 endpoints using requests."""

    def __init__(self, api_key: Optional[str] = None, session: Optional[requests.Session] = None):
        self.api_key = api_key
        self.session = session or requests.Session()

    def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Perform an authenticated GET request to TMDB."""
        if not self.api_key:
            logger.error("Cannot query TMDB: TMDB_API_KEY is not set.")
            return None

        url = f"{TMDB_BASE_URL}{endpoint}"
        query_params = dict(params or {})

        headers = {
            "Accept": "application/json",
            "User-Agent": "LetterboxdStreamingAlert/1.0",
        }

        # Support Bearer token (JWT) or standard 32-char hex API key
        if self.api_key.startswith("ey"):
            headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            query_params["api_key"] = self.api_key

        try:
            resp = self.session.get(url, params=query_params, headers=headers, timeout=10)

            # Handle TMDB rate limiting (429)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 1))
                logger.warning("TMDB rate limit hit. Sleeping for %d seconds...", retry_after)
                time.sleep(retry_after)
                resp = self.session.get(url, params=query_params, headers=headers, timeout=10)

            if resp.status_code == 401:
                logger.error("TMDB Authentication failed (401 Unauthorized). Please check your TMDB_API_KEY.")
                return None

            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            logger.error("TMDB API request failed for %s: %s", url, e)
            return None

    def search_movie(self, title: str, year: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Search TMDB /search/movie by title and optional release year."""
        params: Dict[str, Any] = {"query": title}
        if year:
            params["year"] = year

        data = self._get("/search/movie", params=params)
        if not data or not data.get("results"):
            # If search with year returned nothing, retry without year
            if year:
                logger.debug("No results for '%s (%s)', retrying search without year...", title, year)
                params.pop("year", None)
                data = self._get("/search/movie", params=params)

        if not data or not data.get("results"):
            logger.debug("No TMDB movie found for title: %s", title)
            return None

        results = data["results"]

        # If year was specified, prefer the result matching the year
        if year:
            for item in results:
                rel_date = item.get("release_date", "")
                if rel_date and rel_date.startswith(str(year)):
                    return item

        # Otherwise pick highest popularity result
        return results[0]

    def get_watch_providers(self, tmdb_id: int, region: str = "US") -> Optional[TMDBAvailability]:
        """Query /movie/{tmdb_id}/watch/providers and extract flatrate providers for region."""
        data = self._get(f"/movie/{tmdb_id}/watch/providers")
        if not data or "results" not in data:
            return None

        region_data = data.get("results", {}).get(region, {})
        watch_link = region_data.get("link")
        flatrate_items = region_data.get("flatrate", []) or []

        providers = [
            TMDBProvider(
                provider_id=p.get("provider_id", 0),
                provider_name=p.get("provider_name", ""),
                logo_path=f"https://image.tmdb.org/t/p/original{p['logo_path']}" if p.get("logo_path") else None,
            )
            for p in flatrate_items
            if p.get("provider_name")
        ]

        return TMDBAvailability(
            tmdb_id=tmdb_id,
            title="",
            year=None,
            watch_link=watch_link,
            providers=providers,
        )

    def check_movie(self, title: str, year: Optional[int] = None, region: str = "US", known_tmdb_id: Optional[int] = None) -> Optional[TMDBAvailability]:
        """Search for a movie (or use known ID) and return its streaming providers."""
        tmdb_id = known_tmdb_id
        movie_title = title
        movie_year = year

        if not tmdb_id:
            movie_data = self.search_movie(title, year)
            if not movie_data:
                return None
            tmdb_id = movie_data.get("id")
            movie_title = movie_data.get("title", title)
            rel_date = movie_data.get("release_date", "")
            if rel_date and len(rel_date) >= 4:
                try:
                    movie_year = int(rel_date[:4])
                except ValueError:
                    pass

        if not tmdb_id:
            return None

        avail = self.get_watch_providers(tmdb_id, region=region)
        if avail:
            avail.title = movie_title
            avail.year = movie_year
        return avail


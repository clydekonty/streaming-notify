"""Letterboxd Watchlist parsing using feedparser."""

import html
import logging
import re
from dataclasses import dataclass
from typing import List, Optional
import feedparser

# Try importing curl_cffi for Cloudflare bypass; fallback to standard requests
try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    import requests as cffi_requests
    HAS_CURL_CFFI = False

logger = logging.getLogger(__name__)


@dataclass
class WatchlistFilm:
    """Represents a film extracted from a Letterboxd watchlist."""
    title: str
    year: Optional[int]
    link: Optional[str] = None
    tmdb_id: Optional[int] = None

    def __str__(self) -> str:
        year_str = f" ({self.year})" if self.year else ""
        return f"{self.title}{year_str}"


def parse_film_from_entry(entry: feedparser.FeedParserDict) -> Optional[WatchlistFilm]:
    """Extract clean title and release year from a feedparser entry."""
    title = None
    year = None
    link = entry.get("link")
    tmdb_id = None

    # Check for TMDB movie ID in feed if present
    raw_tmdb = entry.get("tmdb_movieid")
    if raw_tmdb:
        try:
            tmdb_id = int(raw_tmdb)
        except ValueError:
            pass

    # Check letterboxd-specific RSS fields first
    if "letterboxd_filmtitle" in entry and entry.letterboxd_filmtitle:
        title = html.unescape(entry.letterboxd_filmtitle).strip()
    if "letterboxd_filmyear" in entry and entry.letterboxd_filmyear:
        try:
            year = int(str(entry.letterboxd_filmyear).strip())
        except ValueError:
            pass

    # If title not found in specific tag, parse from entry.title
    raw_title = entry.get("title", "")
    if raw_title:
        raw_title = html.unescape(raw_title).strip()
        # Remove rating suffix e.g. " - ★★★★½"
        clean_title = re.sub(r"\s*-\s*[★½\d\.\s]+$", "", raw_title).strip()

        if not title:
            # Check for "Title, Year" pattern (standard Letterboxd RSS)
            m_comma = re.match(r"^(.*?),\s*(\d{4})$", clean_title)
            if m_comma:
                title = m_comma.group(1).strip()
                if year is None:
                    year = int(m_comma.group(2))
            else:
                # Check for "Title (Year)" pattern
                m_paren = re.match(r"^(.*?)\s*\((\d{4})\)$", clean_title)
                if m_paren:
                    title = m_paren.group(1).strip()
                    if year is None:
                        year = int(m_paren.group(2))
                else:
                    title = clean_title

    if not title:
        return None

    return WatchlistFilm(title=title, year=year, link=link, tmdb_id=tmdb_id)


def scrape_watchlist_as_rss_xml(username: str) -> str:
    """
    Letterboxd does not provide an official RSS feed for /watchlist/rss/.
    This function scrapes the public watchlist HTML and synthesizes a valid
    RSS XML document so feedparser can parse the watchlist entries.
    """
    logger.info("Fetching public watchlist pages for user '%s'...", username)
    xml_items = []
    page = 1

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    while True:
        url = (
            f"https://letterboxd.com/{username}/watchlist/page/{page}/"
            if page > 1
            else f"https://letterboxd.com/{username}/watchlist/"
        )

        try:
            if HAS_CURL_CFFI:
                resp = cffi_requests.get(url, headers=headers, impersonate="chrome", timeout=15)
            else:
                resp = cffi_requests.get(url, headers=headers, timeout=15)
        except Exception as e:
            logger.error("Error fetching watchlist page %d: %s", page, e)
            break

        if resp.status_code != 200:
            if page == 1:
                logger.error("Failed to fetch Letterboxd watchlist. HTTP status: %d", resp.status_code)
            break

        # Extract items using regex on HTML attributes
        # Letterboxd posters include data-item-name="Title (Year)" and data-item-link="/film/..."
        items = re.findall(r'data-item-name=\"([^\"]+)\"', resp.text)
        links = re.findall(r'data-item-link=\"([^\"]+)\"', resp.text)

        if not items:
            break

        for i, item_name in enumerate(items):
            unescaped_name = html.unescape(item_name)
            link_path = links[i] if i < len(links) else ""
            full_link = f"https://letterboxd.com{link_path}" if link_path else ""

            # Extract title and year
            m = re.match(r"^(.*?)\s+\((\d{4})\)$", unescaped_name)
            if m:
                film_title = m.group(1).strip()
                film_year = m.group(2)
            else:
                film_title = unescaped_name
                film_year = ""

            escaped_title = html.escape(film_title)
            escaped_link = html.escape(full_link)

            item_xml = f"""    <item>
      <title>{escaped_title}{f", {film_year}" if film_year else ""}</title>
      <link>{escaped_link}</link>
      <letterboxd:filmTitle>{escaped_title}</letterboxd:filmTitle>
      <letterboxd:filmYear>{film_year}</letterboxd:filmYear>
    </item>"""
            xml_items.append(item_xml)

        # Check for next page
        next_page = f"/watchlist/page/{page + 1}/"
        if next_page not in resp.text:
            break
        page += 1

    rss_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:letterboxd="https://letterboxd.com">
  <channel>
    <title>Letterboxd - {username} Watchlist</title>
    <link>https://letterboxd.com/{username}/watchlist/</link>
    <description>Synthesized watchlist feed for {username}</description>
{chr(10).join(xml_items)}
  </channel>
</rss>"""
    return rss_xml


def fetch_watchlist(url: str, username: Optional[str] = None) -> List[WatchlistFilm]:
    """
    Fetch and parse the Letterboxd watchlist using feedparser.

    Supports:
    - Direct RSS feeds (e.g., https://letterboxd.com/<username>/rss/)
    - Watchlist URLs (falls back to scraping HTML and parsing via feedparser)
    - Local XML RSS file paths for testing
    """
    logger.info("Parsing Letterboxd feed from: %s", url)

    # If it's a local file path
    if url.startswith("/") or url.startswith("./") or url.endswith(".xml"):
        feed = feedparser.parse(url)
    elif "watchlist/rss" in url or "watchlist" in url:
        # Letterboxd returns 404/403 for /watchlist/rss/.
        # We fetch the public watchlist and pass synthesized RSS XML to feedparser.
        uname = username or (url.split("letterboxd.com/")[1].split("/")[0] if "letterboxd.com/" in url else "kclyde")
        rss_xml = scrape_watchlist_as_rss_xml(uname)
        feed = feedparser.parse(rss_xml)
    else:
        # Standard RSS feed URL
        feed = feedparser.parse(url)

        # If feedparser failed or got 0 entries on a letterboxd URL, try fallback
        if (getattr(feed, "status", None) in [403, 404] or len(feed.entries) == 0) and "letterboxd.com" in url:
            uname = username or url.split("letterboxd.com/")[1].split("/")[0]
            logger.info("Standard RSS fetch yielded 0 items (status %s). Trying watchlist scraper...", getattr(feed, "status", "unknown"))
            rss_xml = scrape_watchlist_as_rss_xml(uname)
            feed = feedparser.parse(rss_xml)

    films: List[WatchlistFilm] = []
    seen = set()

    for entry in feed.entries:
        film = parse_film_from_entry(entry)
        if film and (film.title, film.year) not in seen:
            seen.add((film.title, film.year))
            films.append(film)

    logger.info("Successfully parsed %d films from watchlist feed.", len(films))
    return films


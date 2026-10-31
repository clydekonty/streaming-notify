"""Streaming provider matching and normalization logic."""

import re
from typing import Dict, List, Optional, Set, Tuple
from src.tmdb import TMDBProvider

# Transactional rental/purchase stores that should NEVER be considered free subscription streaming
TRANSACTIONAL_PROVIDERS: Set[str] = {
    "apple tv store",
    "amazon video",
    "google play movies",
    "youtube",
    "fandango at home",
    "vudu",
    "microsoft store",
    "redbox",
    "spectrum on demand",
}

# Canonical service names mapped to specific allowed provider aliases
SERVICE_MAP: Dict[str, Set[str]] = {
    "criterion channel": {
        "criterion channel",
        "the criterion channel",
        "criterion",
    },
    "netflix": {
        "netflix",
        "netflix standard with ads",
        "netflix basic with ads",
    },
    "max": {
        "max",
        "hbo max",
        "hbo",
    },
    "paramount plus": {
        "paramount plus",
        "paramount+",
        "paramount+ with showtime",
        "paramount plus with showtime",
        "paramount plus premium",
        "paramount plus essential",
    },
    "peacock": {
        "peacock",
        "peacock premium",
        "peacock premium plus",
        "peacock plus",
    },
    "disney plus": {
        "disney plus",
        "disney+",
    },
    "hulu": {
        "hulu",
    },
    "apple tv plus": {
        "apple tv plus",
        "apple tv+",
        "apple tv",  # TMDB ID 350 for Apple TV+ subscription
    },
    "amazon prime video": {
        "amazon prime video",
        "prime video",
        "amazon prime video with ads",
        "amazon prime video free with ads",
    },
}


def normalize_service_name(name: str) -> str:
    """Normalize service name by replacing symbols and stripping punctuation."""
    s = name.lower()
    # Replace '+' with ' plus '
    s = s.replace("+", " plus ")
    # Replace non-alphanumeric with spaces
    s = re.sub(r"[^\w\s]", " ", s)
    # Collapse multiple spaces
    return " ".join(s.split())


def match_service(target_service: str, provider_name: str) -> bool:
    """
    Check if a provider returned by TMDB matches one of the user's target subscriptions.

    Crucially distinguishes between:
    - Included subscription streaming (e.g. Apple TV+, Amazon Prime Video)
    - Rental/Purchase stores (e.g. Apple TV Store, Amazon Video)
    - Add-on channels (e.g. 'Cinemax Apple TV channel' is Cinemax, NOT Apple TV+)
    """
    norm_target = normalize_service_name(target_service)
    norm_prov = normalize_service_name(provider_name)

    # 1. Never match transactional rent/buy stores
    if norm_prov in TRANSACTIONAL_PROVIDERS:
        return False

    # 2. Decompose channel add-on providers
    # E.g., 'Cinemax Apple TV channel' -> core network is 'Cinemax'
    # E.g., 'Apple TV Amazon Channel' -> core network is 'Apple TV'
    # E.g., 'HBO Max Amazon Channel' -> core network is 'HBO Max'
    channel_pattern = r"^(.*?)\s+(?:apple tv channel|amazon channel|roku channel|roku premium channel)$"
    channel_match = re.search(channel_pattern, norm_prov, re.IGNORECASE)
    if channel_match:
        core_service = channel_match.group(1).strip()
    else:
        core_service = norm_prov

    # 3. Find canonical service key for target_service
    target_canonical = None
    for canonical, aliases in SERVICE_MAP.items():
        if norm_target == normalize_service_name(canonical) or any(
            norm_target == normalize_service_name(a) for a in aliases
        ):
            target_canonical = canonical
            break

    # If target is custom and not in SERVICE_MAP
    if not target_canonical:
        return norm_target == core_service

    allowed_aliases = {normalize_service_name(a) for a in SERVICE_MAP[target_canonical]}

    # 4. Check core service against allowed aliases
    if core_service in allowed_aliases:
        return True

    # 5. Word-boundary match on core service only
    for alias in allowed_aliases:
        if re.search(r"\b" + re.escape(alias) + r"\b", core_service):
            # Guard against Cinemax accidentally matching Max
            if target_canonical == "max" and "cinemax" in core_service:
                continue
            return True

    return False


def find_matched_services(
    target_services: List[str], providers: List[TMDBProvider]
) -> List[Tuple[str, TMDBProvider]]:
    """
    Given a list of target services and TMDB providers for a movie,
    return a deduplicated list of tuples: (matched_target_service, tmdb_provider).
    """
    matches = []
    matched_targets = set()

    for provider in providers:
        for target in target_services:
            if target in matched_targets:
                continue
            if match_service(target, provider.provider_name):
                matches.append((target, provider))
                matched_targets.add(target)

    return matches

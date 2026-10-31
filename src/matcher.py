"""Streaming provider matching and normalization logic."""

import re
from typing import Dict, List, Optional, Tuple
from src.tmdb import TMDBProvider

# Canonical service names mapped to common provider aliases and variations
SERVICE_ALIASES: Dict[str, List[str]] = {
    "criterion channel": [
        "criterion channel",
        "the criterion channel",
        "criterion",
    ],
    "netflix": [
        "netflix",
        "netflix basic with ads",
    ],
    "max": [
        "max",
        "hbo max",
        "hbo",
        "max amazon channel",
    ],
    "paramount plus": [
        "paramount plus",
        "paramount+",
        "paramount+ with showtime",
        "paramount plus with showtime",
        "paramount+ amazon channel",
        "paramount plus apple tv channel",
    ],
    "peacock": [
        "peacock",
        "peacock premium",
        "peacock premium plus",
        "peacock plus",
    ],
    "disney plus": [
        "disney plus",
        "disney+",
    ],
    "hulu": [
        "hulu",
    ],
    "apple tv plus": [
        "apple tv plus",
        "apple tv+",
        "apple tv",
    ],
    "amazon prime video": [
        "amazon prime video",
        "prime video",
        "amazon video",
        "amazon prime video with ads",
    ],
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
    Check if a provider returned by TMDB matches one of the user's target services.

    Handles:
    - Normalization of punctuation, casing, '+' vs 'plus'
    - Known aliases (e.g. 'Prime Video' -> 'Amazon Prime Video')
    - Word boundary checks (prevents 'Max' matching 'Cinemax')
    """
    norm_target = normalize_service_name(target_service)
    norm_prov = normalize_service_name(provider_name)

    # 1. Direct equality
    if norm_target == norm_prov:
        return True

    # 2. Check predefined canonical aliases
    for canonical, aliases in SERVICE_ALIASES.items():
        norm_canonical = normalize_service_name(canonical)
        norm_aliases = [normalize_service_name(a) for a in aliases]

        # Is the target service part of this alias group?
        if norm_target == norm_canonical or norm_target in norm_aliases:
            # Check if provider name matches any alias in the group
            for alias in norm_aliases:
                if alias == norm_prov:
                    return True
                # Match full phrase as word boundaries e.g. "paramount plus" in "paramount plus with showtime"
                if re.search(r"\b" + re.escape(alias) + r"\b", norm_prov):
                    return True

    # 3. Multi-word boundary matching (for custom services not in aliases)
    if " " in norm_target and re.search(r"\b" + re.escape(norm_target) + r"\b", norm_prov):
        return True
    if " " in norm_prov and re.search(r"\b" + re.escape(norm_prov) + r"\b", norm_target):
        return True

    return False


def find_matched_services(
    target_services: List[str], providers: List[TMDBProvider]
) -> List[Tuple[str, TMDBProvider]]:
    """
    Given a list of target services and TMDB providers for a movie,
    return a list of tuples: (matched_target_service, tmdb_provider).
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


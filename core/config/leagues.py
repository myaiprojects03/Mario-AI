from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional


@dataclass(frozen=True)
class LeagueConfig:
    """Dataclass holding single-source-of-truth configuration for a sports league."""

    name: str
    sport: str  # "fifa" or "ebasket"
    duration_minutes: int
    quirks: Dict[str, Any] = field(default_factory=dict)


# Master registry of all 6 leagues in the system
LEAGUES: Dict[str, LeagueConfig] = {
    "Esoccer Battle": LeagueConfig(
        name="Esoccer Battle",
        sport="fifa",
        duration_minutes=8,
        quirks={"has_ht_odds": True, "period_format": "2x4min"},
    ),
    "Esoccer H2H GG League": LeagueConfig(
        name="Esoccer H2H GG League",
        sport="fifa",
        duration_minutes=8,
        quirks={"has_ht_odds": True, "period_format": "2x4min"},
    ),
    "Esoccer Battle Volta": LeagueConfig(
        name="Esoccer Battle Volta",
        sport="fifa",
        duration_minutes=6,
        quirks={"has_ht_odds": True, "period_format": "2x3min"},
    ),
    "Esoccer GT Leagues": LeagueConfig(
        name="Esoccer GT Leagues",
        sport="fifa",
        duration_minutes=12,
        quirks={"has_ht_odds": True, "period_format": "2x6min"},
    ),
    "eBasketball H2H GG League": LeagueConfig(
        name="eBasketball H2H GG League",
        sport="ebasket",
        duration_minutes=20,
        quirks={"has_ht_odds": True, "period_format": "4x5min"},
    ),
    "eBasketball Battle": LeagueConfig(
        name="eBasketball Battle",
        sport="ebasket",
        duration_minutes=20,
        quirks={"has_ht_odds": True, "period_format": "4x5min"},
    ),
}


def get_league_config(league_name: str) -> Optional[LeagueConfig]:
    """Retrieve LeagueConfig by exact or substring matching on league_name."""
    if not league_name:
        return None

    # Sort keys by length descending to match specific keys ("Esoccer Battle Volta") before broader keys ("Esoccer Battle")
    sorted_keys = sorted(LEAGUES.keys(), key=len, reverse=True)
    for key in sorted_keys:
        if key.lower() in league_name.lower():
            return LEAGUES[key]

    return None


def get_duration_minutes(league_name: str, sport: str) -> int:
    """Lookup match duration minutes for a given league name and sport."""
    config = get_league_config(league_name)
    if config:
        return config.duration_minutes
    return 8 if sport == "fifa" else 20


def list_leagues_by_sport(sport: str) -> List[LeagueConfig]:
    """List all registered LeagueConfig objects for a specific sport."""
    return [config for config in LEAGUES.values() if config.sport == sport]

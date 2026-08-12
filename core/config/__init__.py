"""Configuration module providing central application settings."""

from core.config.settings import settings
from core.config.leagues import (
    LeagueConfig,
    LEAGUES,
    get_league_config,
    get_duration_minutes,
    list_leagues_by_sport,
)

__all__ = [
    "settings",
    "LeagueConfig",
    "LEAGUES",
    "get_league_config",
    "get_duration_minutes",
    "list_leagues_by_sport",
]

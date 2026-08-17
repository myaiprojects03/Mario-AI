import time
import logging
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

import requests
from sqlalchemy.orm import Session
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from core.config.settings import settings
from core.db.models import Match, Odds, Result

logger = logging.getLogger("core.ingestion.jarbet_client")
logging.basicConfig(level=logging.INFO)


class JarBetServerError(requests.HTTPError):
    """Custom exception raised for JarBet 5xx server errors to trigger retries."""
    pass


class JarBetClient:
    """Client for interacting with the JarBet virtual sports API."""

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.base_url = (base_url or settings.JARBET_BASE_URL or "https://api.jarbet.example.com").rstrip("/")
        self.api_key = api_key or settings.JARBET_API_KEY
        
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({
                "x-api-key": self.api_key,
                "Accept": "application/json",
            })
        
        # Adaptive rate limiting configuration
        self.min_interval = 1.0  # Conservative start: 1 second between requests
        self.last_request_time = 0.0

    def _enforce_rate_limit(self):
        """Enforce min_interval spacing between API requests."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_interval:
            sleep_duration = self.min_interval - elapsed
            logger.debug(f"Rate limiter pausing for {sleep_duration:.2f}s")
            time.sleep(sleep_duration)

    def _inspect_rate_limit_headers(self, response: requests.Response):
        """Extract and log rate limit headers from API responses to determine limits empirically."""
        headers = response.headers
        remaining = headers.get("X-RateLimit-Remaining")
        limit = headers.get("X-RateLimit-Limit")
        reset = headers.get("X-RateLimit-Reset")
        retry_after = headers.get("Retry-After")

        logger.info(
            f"API Request [{response.status_code}] {response.url} | "
            f"RateLimit-Remaining: {remaining}, Limit: {limit}, Reset: {reset}, Retry-After: {retry_after}"
        )

        # Adaptively slow down request interval if remaining tokens are low
        if remaining is not None:
            try:
                rem_val = int(remaining)
                if rem_val == 0:
                    self.min_interval = max(self.min_interval * 2, 5.0)
                elif rem_val < 5:
                    self.min_interval = max(self.min_interval, 2.0)
                else:
                    self.min_interval = min(self.min_interval, 1.0)
            except ValueError:
                pass

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=0.01, min=0.01, max=1.0),
        retry=retry_if_exception_type((requests.RequestException, JarBetServerError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _execute_request(self, method: str, endpoint: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
        """Execute an HTTP request with adaptive rate limiting and exponential backoff retry."""
        url = f"{self.base_url}{endpoint}"
        max_429_retries = 3
        attempt_429 = 0

        while True:
            self._enforce_rate_limit()
            self.last_request_time = time.time()

            try:
                response = self.session.request(method, url, params=params, timeout=10.0)
                self._inspect_rate_limit_headers(response)

                if response.status_code == 429:
                    attempt_429 += 1
                    retry_after_str = response.headers.get("Retry-After")
                    try:
                        backoff = float(retry_after_str) if retry_after_str else (1.5 ** attempt_429 * 2.0)
                    except ValueError:
                        backoff = 1.5 ** attempt_429 * 2.0

                    logger.warning(
                        f"Received 429 Too Many Requests on {url}. "
                        f"Backing off for {backoff:.2f}s (Attempt {attempt_429}/{max_429_retries})"
                    )
                    self.min_interval = max(self.min_interval * 2.0, 3.0)
                    if attempt_429 > max_429_retries:
                        response.raise_for_status()
                    time.sleep(backoff)
                    continue

                if response.status_code >= 500:
                    raise JarBetServerError(f"Server error {response.status_code}: {response.text}")

                response.raise_for_status()
                return response

            except requests.RequestException as err:
                logger.error(f"Network error accessing {url}: {err}")
                raise

    # -------------------------------------------------------------------
    # Endpoints
    # -------------------------------------------------------------------

    def get_fifa_pre(self) -> List[Dict[str, Any]]:
        """GET /matches/pre - live pre-match data for eSoccer FIFA."""
        resp = self._execute_request("GET", "/matches/pre")
        data = resp.json()
        return data.get("matches", data) if isinstance(data, dict) else data

    def get_ebasket_pre(self) -> List[Dict[str, Any]]:
        """GET /matches/ebasket/pre - live pre-match data for eBasketball."""
        resp = self._execute_request("GET", "/matches/ebasket/pre")
        data = resp.json()
        return data.get("matches", data) if isinstance(data, dict) else data

    def get_fifa_history(self) -> List[Dict[str, Any]]:
        """GET /history/pre - historical backfill data for eSoccer FIFA."""
        resp = self._execute_request("GET", "/history/pre")
        data = resp.json()
        return data.get("matches", data) if isinstance(data, dict) else data

    def get_ebasket_history(self) -> List[Dict[str, Any]]:
        """GET /history/ebasket/pre - historical backfill data for eBasketball."""
        resp = self._execute_request("GET", "/history/ebasket/pre")
        data = resp.json()
        return data.get("matches", data) if isinstance(data, dict) else data

    # -------------------------------------------------------------------
    # Database Parsing & Upsert
    # -------------------------------------------------------------------

    def _generate_match_id(self, item: Dict[str, Any], sport: str) -> str:
        """
        Extract match_id or generate a stable natural key hash if not explicitly provided.
        Supports _id, idMatchBet365, match_id, id, game_id.
        """
        if "_id" in item and item["_id"]:
            return str(item["_id"])
        if "idMatchBet365" in item and item["idMatchBet365"]:
            return str(item["idMatchBet365"])
        if "match_id" in item and item["match_id"]:
            return str(item["match_id"])
        if "id" in item and item["id"]:
            return str(item["id"])
        if "game_id" in item and item["game_id"]:
            return str(item["game_id"])

        # Natural key fallback
        league = item.get("league", "unknown")
        home = item.get("home_team", item.get("home", ""))
        away = item.get("away_team", item.get("away", ""))
        start_time = item.get("startedAt", item.get("match_start_time", item.get("start_time", "")))
        raw_str = f"{sport}:{league}:{home}:{away}:{start_time}"
        return hashlib.md5(raw_str.encode("utf-8")).hexdigest()

    def upsert_match_data(
        self, records: List[Dict[str, Any]], sport: str, db_session: Session, default_source: str = "jarbet_live"
    ) -> List[Match]:
        """
        Parse raw API response items and upsert into core.matches, core.odds, and core.results.
        Handles both nested live/history API JSON payloads and flat backfill payloads.
        """
        upserted_matches = []
        if not isinstance(records, list):
            logger.error(f"Expected list of records, got {type(records)}")
            return upserted_matches

        for idx, item in enumerate(records, start=1):
            if not isinstance(item, dict):
                logger.warning(f"Skipping malformed non-dict record: {item}")
                continue

            try:
                match_id = self._generate_match_id(item, sport)
                league = item.get("league", "Unknown League")

                # Handle nested home / away objects or flat strings
                home_raw = item.get("home")
                away_raw = item.get("away")

                if isinstance(home_raw, dict):
                    home_player = home_raw.get("name", item.get("home_player"))
                    home_team = home_raw.get("teamName", item.get("home_team", "Home Team"))
                    home_goals = home_raw.get("goals")
                else:
                    home_player = item.get("home_player")
                    home_team = item.get("home_team", home_raw if isinstance(home_raw, str) else "Home Team")
                    home_goals = item.get("final_home_score", item.get("home_score"))

                if isinstance(away_raw, dict):
                    away_player = away_raw.get("name", item.get("away_player"))
                    away_team = away_raw.get("teamName", item.get("away_team", "Away Team"))
                    away_goals = away_raw.get("goals")
                else:
                    away_player = item.get("away_player")
                    away_team = item.get("away_team", away_raw if isinstance(away_raw, str) else "Away Team")
                    away_goals = item.get("final_away_score", item.get("away_score"))

                duration = item.get("duration_minutes")
                source = item.get("source", default_source)

                start_time_str = item.get("startedAt") or item.get("match_start_time") or item.get("start_time")
                if start_time_str and isinstance(start_time_str, str):
                    try:
                        start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
                    except ValueError:
                        start_time = datetime.now(timezone.utc)
                else:
                    start_time = datetime.now(timezone.utc)

                # Query existing match for upsert
                existing_match = db_session.query(Match).filter_by(match_id=match_id).first()
                if existing_match:
                    existing_match.sport = sport
                    existing_match.league = league
                    existing_match.home_player = home_player
                    existing_match.away_player = away_player
                    existing_match.home_team = home_team
                    existing_match.away_team = away_team
                    existing_match.match_start_time = start_time
                    existing_match.duration_minutes = duration
                    if existing_match.source != "csv_backfill":
                        existing_match.source = source
                    existing_match.raw_payload = item
                    match_obj = existing_match
                else:
                    match_obj = Match(
                        match_id=match_id,
                        sport=sport,
                        league=league,
                        home_player=home_player,
                        away_player=away_player,
                        home_team=home_team,
                        away_team=away_team,
                        match_start_time=start_time,
                        duration_minutes=duration,
                        source=source,
                        raw_payload=item,
                    )
                    db_session.add(match_obj)

                # Upsert Result if scores are present and non-null
                if home_goals is not None and away_goals is not None:
                    try:
                        h_score = int(home_goals)
                        a_score = int(away_goals)
                        existing_res = db_session.query(Result).filter_by(match_id=match_id).first()
                        if existing_res:
                            existing_res.final_home_score = h_score
                            existing_res.final_away_score = a_score
                            existing_res.settled_at = start_time
                            existing_res.settlement_source = source
                        else:
                            res_obj = Result(
                                match_id=match_id,
                                final_home_score=h_score,
                                final_away_score=a_score,
                                settled_at=start_time,
                                settlement_source=source,
                            )
                            db_session.add(res_obj)
                    except (ValueError, TypeError):
                        pass

                # Parse attached odds if present in payload (supports dict or list)
                odds_data = item.get("odds", {})
                if isinstance(odds_data, dict):
                    # Nested odds object: {"over_under": {...}, "money_line": {...}, ...}
                    for mkt_key, mkt_val in odds_data.items():
                        if not isinstance(mkt_val, dict):
                            continue
                        m_name = f"{sport}_{mkt_key}" if not mkt_key.startswith(sport) else mkt_key
                        line_val = mkt_val.get("line")
                        odds_close_val = mkt_val.get("over") or mkt_val.get("home")
                        odds_obj = Odds(
                            match_id=match_id,
                            market_type=m_name,
                            line_value=float(line_val) if line_val is not None else None,
                            odds_open=float(mkt_val.get("odds_open")) if mkt_val.get("odds_open") is not None else None,
                            odds_close=float(odds_close_val) if odds_close_val is not None else None,
                            odds_snapshot_time=datetime.now(timezone.utc),
                            side="over" if "over" in mkt_val else "home",
                        )
                        db_session.add(odds_obj)

                elif isinstance(odds_data, list):
                    # List of dicts schema
                    for o_item in odds_data:
                        if not isinstance(o_item, dict):
                            continue
                        odds_obj = Odds(
                            match_id=match_id,
                            market_type=o_item.get("market_type", f"{sport}_money_line"),
                            line_value=o_item.get("line_value"),
                            odds_open=o_item.get("odds_open"),
                            odds_close=o_item.get("odds_close"),
                            odds_snapshot_time=datetime.now(timezone.utc),
                            side=o_item.get("side", "home"),
                        )
                        db_session.add(odds_obj)
                upserted_matches.append(match_obj)

                if idx % 500 == 0:
                    db_session.commit()

            except Exception as err:
                db_session.rollback()
                logger.error(f"Malformed payload encountered. Skipping record {item}: {err}")
                continue

        db_session.commit()
        return upserted_matches


# -------------------------------------------------------------------
# Empirical Detection & Reporting Functions
# -------------------------------------------------------------------

def detect_odds_snapshot_behavior(
    first_poll_record: Dict[str, Any],
    second_poll_record: Dict[str, Any],
    findings_file: str = "core/ingestion/FINDINGS.md",
) -> Dict[str, Any]:
    """
    Compares odds for the same match across two polls to empirically detect
    whether JarBet pre-match odds update dynamically or remain static snapshots.
    """
    match_id = first_poll_record.get("match_id", first_poll_record.get("_id", first_poll_record.get("id", "unknown")))
    
    odds1 = first_poll_record.get("odds", {})
    odds2 = second_poll_record.get("odds", {})

    is_dynamic = (odds1 != odds2)
    behavior_type = "Dynamic Updates Across Polls" if is_dynamic else "Single Static Snapshot"

    diff_details = {}
    if is_dynamic and isinstance(odds1, dict) and isinstance(odds2, dict):
        for k in set(list(odds1.keys()) + list(odds2.keys())):
            if odds1.get(k) != odds2.get(k):
                diff_details[k] = {"poll_1": odds1.get(k), "poll_2": odds2.get(k)}

    return {
        "match_id": match_id,
        "is_dynamic": is_dynamic,
        "behavior_type": behavior_type,
        "diff_details": diff_details,
    }


def analyze_half_time_odds_presence(
    matches: List[Dict[str, Any]],
    findings_file: str = "core/ingestion/FINDINGS.md",
) -> Dict[str, Any]:
    """
    Analyzes presence of Half-Time odds (e.g. asian_handicap_ht or over_under_ht)
    across all matches, broken down by league.
    """
    league_stats = {}

    for item in matches:
        if not isinstance(item, dict):
            continue
        league = item.get("league", "Unknown League")
        odds = item.get("odds", {})

        has_ht = (
            "asian_handicap_ht" in item or "over_under_ht" in item or
            (isinstance(odds, dict) and ("asian_handicap_ht" in odds or "over_under_ht" in odds or "ht" in str(odds).lower())) or
            (isinstance(odds, list) and any("ht" in str(o.get("market_type", "")).lower() for o in odds if isinstance(o, dict)))
        )

        if league not in league_stats:
            league_stats[league] = {"total": 0, "present": 0}

        league_stats[league]["total"] += 1
        if has_ht:
            league_stats[league]["present"] += 1

    summary = {}
    for lg, counts in league_stats.items():
        total = counts["total"]
        present = counts["present"]
        rate = (present / total) * 100.0 if total > 0 else 0.0
        summary[lg] = {
            "total": total,
            "present": present,
            "rate": round(rate, 2),
            "pattern": "Consistently Offered" if rate > 80.0 else ("Partially Offered" if rate > 0 else "Not Offered"),
        }

    return summary

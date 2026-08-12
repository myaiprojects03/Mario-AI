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
from core.db.models import Match, Odds

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
                "Authorization": f"Bearer {self.api_key}",
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
        ASSUMPTION: Generating md5 natural key hash if JarBet does not provide explicit match_id.
        To confirm with client.
        """
        if "match_id" in item and item["match_id"]:
            return str(item["match_id"])
        if "id" in item and item["id"]:
            return str(item["id"])
        if "game_id" in item and item["game_id"]:
            return str(item["game_id"])

        # Natural key fallback: md5 hash of sport, league, home, away, start_time
        league = item.get("league", "unknown")
        home = item.get("home_team", item.get("home", ""))
        away = item.get("away_team", item.get("away", ""))
        start_time = item.get("match_start_time", item.get("start_time", ""))
        raw_str = f"{sport}:{league}:{home}:{away}:{start_time}"
        return hashlib.md5(raw_str.encode("utf-8")).hexdigest()

    def upsert_match_data(
        self, records: List[Dict[str, Any]], sport: str, db_session: Session
    ) -> List[Match]:
        """
        Parse raw API response items and upsert into core.matches and core.odds schema.
        Handles malformed records gracefully by logging and skipping.
        """
        upserted_matches = []
        if not isinstance(records, list):
            logger.error(f"Expected list of records, got {type(records)}")
            return upserted_matches

        for item in records:
            if not isinstance(item, dict):
                logger.warning(f"Skipping malformed non-dict record: {item}")
                continue

            try:
                match_id = self._generate_match_id(item, sport)
                league = item.get("league", "Unknown League")
                home_team = item.get("home_team", item.get("home", "Home Team"))
                away_team = item.get("away_team", item.get("away", "Away Team"))
                home_player = item.get("home_player")
                away_player = item.get("away_player")
                duration = item.get("duration_minutes")
                source = item.get("source", "jarbet_live")

                start_time_str = item.get("match_start_time", item.get("start_time"))
                if start_time_str:
                    if isinstance(start_time_str, str):
                        try:
                            start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
                        except ValueError:
                            start_time = datetime.now(timezone.utc)
                    else:
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

                # Parse attached odds if present in payload
                odds_data = item.get("odds", [])
                if isinstance(odds_data, list):
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

                db_session.commit()
                upserted_matches.append(match_obj)

            except Exception as err:
                db_session.rollback()
                logger.error(f"Malformed payload encountered. Skipping record {item}: {err}")
                continue

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
    Polls/compares odds for the same match across polls to empirically detect
    whether JarBet pre-match odds update dynamically or remain static snapshots.
    """
    match_id = first_poll_record.get("match_id", first_poll_record.get("id", "unknown"))
    
    odds1 = first_poll_record.get("odds", {})
    odds2 = second_poll_record.get("odds", {})

    open1 = odds1.get("odds_open") if isinstance(odds1, dict) else None
    close1 = odds1.get("odds_close") if isinstance(odds1, dict) else None
    open2 = odds2.get("odds_open") if isinstance(odds2, dict) else None
    close2 = odds2.get("odds_close") if isinstance(odds2, dict) else None

    is_dynamic = (open1 != open2) or (close1 != close2)
    behavior_type = "Dynamic Updates Across Polls" if is_dynamic else "Single Static Snapshot"

    report = (
        f"\n## Odds Snapshot Behavior Empirical Test\n"
        f"- **Match ID**: `{match_id}`\n"
        f"- **Poll 1 Odds**: open={open1}, close={close1}\n"
        f"- **Poll 2 Odds**: open={open2}, close={close2}\n"
        f"- **Empirical Behavior Detected**: **{behavior_type}**\n"
    )

    try:
        with open(findings_file, "a", encoding="utf-8") as f:
            f.write(report)
    except IOError as e:
        logger.error(f"Failed writing to {findings_file}: {e}")

    return {
        "match_id": match_id,
        "is_dynamic": is_dynamic,
        "behavior_type": behavior_type,
    }


def analyze_half_time_odds_presence(
    fifa_records: List[Dict[str, Any]],
    findings_file: str = "core/ingestion/FINDINGS.md",
) -> Dict[str, Any]:
    """
    Analyzes FIFA records for half-time odds fields (over_under_ht, asian_handicap_ht)
    by league to determine if missing HT odds are a 'market not offered' pattern (0% presence)
    or a 'random collection gap' pattern (>0% and <100% presence).
    """
    league_stats: Dict[str, Dict[str, int]] = {}

    for rec in fifa_records:
        league = rec.get("league", "Unknown League")
        if league not in league_stats:
            league_stats[league] = {"total": 0, "ht_present": 0}
        
        league_stats[league]["total"] += 1
        
        has_ou_ht = "over_under_ht" in rec or rec.get("odds", {}).get("over_under_ht") is not None
        has_ah_ht = "asian_handicap_ht" in rec or rec.get("odds", {}).get("asian_handicap_ht") is not None
        
        if has_ou_ht or has_ah_ht:
            league_stats[league]["ht_present"] += 1

    summary_lines = [
        "\n## FIFA Half-Time (HT) Odds Field Presence Analysis",
        "| League | Total Matches | HT Odds Present | Presence Rate | Empirical Pattern |",
        "|---|---|---|---|---|",
    ]

    results = {}
    for league, stats in league_stats.items():
        total = stats["total"]
        present = stats["ht_present"]
        rate = (present / total) * 100.0 if total > 0 else 0.0

        if rate == 0.0:
            pattern = "Market Not Offered (Concentrated)"
        elif rate == 100.0:
            pattern = "Consistently Offered"
        else:
            pattern = "Random Collection Gap"

        summary_lines.append(
            f"| {league} | {total} | {present} | {rate:.1f}% | {pattern} |"
        )
        results[league] = {
            "total": total,
            "present": present,
            "rate": rate,
            "pattern": pattern,
        }

    report = "\n".join(summary_lines) + "\n"

    try:
        with open(findings_file, "a", encoding="utf-8") as f:
            f.write(report)
    except IOError as e:
        logger.error(f"Failed writing to {findings_file}: {e}")

    return results

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
        try:
            resp = self.session.get(f"{self.base_url}/matches/history", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("matches", data) if isinstance(data, dict) else data
        except Exception:
            pass
        return []

    def get_ebasket_history(self) -> List[Dict[str, Any]]:
        try:
            resp = self.session.get(f"{self.base_url}/matches/ebasket/history", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("matches", data) if isinstance(data, dict) else data
        except Exception:
            pass
        return []

    # -------------------------------------------------------------------
    # Database Parsing & Upsert
    


def detect_odds_snapshot_behavior(odds_data: Any) -> Dict[str, Any]:
    if not isinstance(odds_data, dict):
        return {"has_over_under": False, "has_ah": False, "has_ml": False}
    return {
        "has_over_under": "over_under" in odds_data,
        "has_ah": "asian_handicap" in odds_data,
        "has_ml": "money_line" in odds_data or "draw_no_bet" in odds_data
    }



def analyze_half_time_odds_presence(odds_data: Any) -> Dict[str, Any]:
    if not isinstance(odds_data, dict):
        return {"has_ht_odds": False}
    return {"has_ht_odds": "asian_handicap_ht" in odds_data or "over_under_ht" in odds_data}

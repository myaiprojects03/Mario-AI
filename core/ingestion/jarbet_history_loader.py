import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple, Set

from sqlalchemy.orm import Session
from sqlalchemy import select, or_

from core.config.settings import settings
from core.db.models import Match, Result, Odds
from core.ingestion.jarbet_client import JarBetClient

logger = logging.getLogger("core.ingestion.jarbet_history_loader")
logging.basicConfig(level=logging.INFO)

# Default seed players to ensure history endpoints return full historical range even if DB is fresh
DEFAULT_FIFA_PLAYERS = [
    "Bomb1to", "KraftVK", "Furious", "TUSK", "labotryas", "Carlos", "dm1trena",
    "Legion", "Ultrex", "kirman", "ENT", "Xoma", "s1mple", "dor1an", "Kev1n"
]

DEFAULT_EBASKET_PLAYERS = [
    "JD", "CHARM", "MARINE", "OREZ", "KNIGHT", "SUPERIOR", "KARMA", "CYPHER",
    "TAAPZ", "PULSE", "DIMES", "LAKERS", "BULLS", "CELTICS"
]


class JarBetHistoryLoader:
    """
    Historical data loader for JarBet eSoccer and eBasketball endpoints:
    - GET /history/pre (eSoccer FIFA)
    - GET /history/ebasket/pre (eBasketball)
    """

    def __init__(self, client: Optional[JarBetClient] = None):
        self.client = client or JarBetClient()

    def get_distinct_players(self, db_session: Optional[Session], sport: str) -> List[str]:
        """Queries distinct player names from DB matches table for the given sport."""
        players: Set[str] = set()

        # Seed defaults
        if sport.lower() == "fifa":
            players.update(DEFAULT_FIFA_PLAYERS)
        else:
            players.update(DEFAULT_EBASKET_PLAYERS)

        if db_session:
            try:
                query = select(Match.home_player, Match.away_player).where(Match.sport == sport)
                rows = db_session.execute(query).fetchall()
                for h_p, a_p in rows:
                    if h_p:
                        players.add(str(h_p).strip())
                    if a_p:
                        players.add(str(a_p).strip())
            except Exception as e:
                logger.warning(f"Error querying distinct players from database: {e}")

        return sorted(list(players))

    def fetch_historical_records_for_sport(
        self, sport: str, db_session: Optional[Session] = None
    ) -> List[Dict[str, Any]]:
        """
        Iterates through distinct players calling JarBet historical API endpoints.
        Dynamically tracks newly discovered players from returned payloads to maximize coverage.
        """
        endpoint = "/history/pre" if sport.lower() == "fifa" else "/history/ebasket/pre"
        known_players = set(self.get_distinct_players(db_session, sport))
        queried_players: Set[str] = set()
        accumulated_matches: Dict[str, Dict[str, Any]] = {}

        player_queue = list(known_players)

        while player_queue:
            player = player_queue.pop(0)
            if player in queried_players or not player:
                continue

            queried_players.add(player)
            logger.info(f"Fetching {sport} history for player '{player}' from {endpoint}...")

            try:
                resp = self.client._execute_request("GET", endpoint, params={"homeName": player})
                data = resp.json()
                items = data.get("matches", data) if isinstance(data, dict) else data

                if isinstance(items, list):
                    logger.info(f"Received {len(items)} records for player '{player}'.")
                    for m in items:
                        if not isinstance(m, dict):
                            continue
                        m_id = self.client._generate_match_id(m, sport)
                        accumulated_matches[m_id] = m

                        # Dynamically discover new player names from payload
                        home_obj = m.get("home", {})
                        away_obj = m.get("away", {})

                        if isinstance(home_obj, dict) and home_obj.get("name"):
                            p_name = str(home_obj["name"]).strip()
                            if p_name and p_name not in queried_players and p_name not in known_players:
                                known_players.add(p_name)
                                player_queue.append(p_name)

                        if isinstance(away_obj, dict) and away_obj.get("name"):
                            p_name = str(away_obj["name"]).strip()
                            if p_name and p_name not in queried_players and p_name not in known_players:
                                known_players.add(p_name)
                                player_queue.append(p_name)

            except Exception as err:
                logger.error(f"Error fetching history for player '{player}': {err}")

        logger.info(f"Completed history pull for {sport}. Total unique match records: {len(accumulated_matches)}")
        return list(accumulated_matches.values())

    def filter_confirmed_results(
        self, records: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Validates records to ensure they have confirmed final scores.
        Only keeps records where home goals and away goals are non-null integers >= 0.
        Skips and logs any record missing a confirmed final score.
        """
        valid_records = []
        skipped_records = []

        for item in records:
            if not isinstance(item, dict):
                skipped_records.append(item)
                continue

            home_raw = item.get("home")
            away_raw = item.get("away")

            h_goals = home_raw.get("goals") if isinstance(home_raw, dict) else item.get("final_home_score", item.get("home_score"))
            a_goals = away_raw.get("goals") if isinstance(away_raw, dict) else item.get("final_away_score", item.get("away_score"))

            if h_goals is None or a_goals is None:
                skipped_records.append(item)
                match_id = item.get("_id") or item.get("idMatchBet365") or item.get("match_id")
                logger.warning(f"Skipping record '{match_id}' - Missing confirmed final score (home={h_goals}, away={a_goals}).")
                continue

            try:
                h_int = int(h_goals)
                a_int = int(a_goals)
                if h_int >= 0 and a_int >= 0:
                    valid_records.append(item)
                else:
                    skipped_records.append(item)
                    logger.warning(f"Skipping record - Invalid negative score: home={h_int}, away={a_int}.")
            except (ValueError, TypeError):
                skipped_records.append(item)
                logger.warning(f"Skipping record - Non-integer score: home={h_goals}, away={a_goals}.")

        logger.info(f"Result validation complete: {len(valid_records)} valid records, {len(skipped_records)} skipped incomplete records.")
        return valid_records, skipped_records

    def ingest_sport_history(
        self, sport: str, db_session: Session
    ) -> Dict[str, Any]:
        """
        Full ingestion pipeline for a single sport:
        1. Pulls historical records from JarBet API.
        2. Filters for confirmed final results.
        3. Upserts records into core.matches (source='jarbet_history'), core.odds, core.results.
        4. Calculates overlap metrics against existing csv_backfill matches.
        """
        raw_records = self.fetch_historical_records_for_sport(sport, db_session)
        valid_records, skipped_records = self.filter_confirmed_results(raw_records)

        # Upsert with source='jarbet_history'
        upserted_matches = self.client.upsert_match_data(
            records=valid_records,
            sport=sport,
            db_session=db_session,
            default_source="jarbet_history",
        )

        ingested_ids = {m.match_id for m in upserted_matches}

        # Analyze overlap and coverage for this sport
        report = self.compute_overlap_metrics(
            db_session=db_session,
            sport=sport,
            raw_pulled_count=len(raw_records),
            valid_count=len(valid_records),
            skipped_count=len(skipped_records),
            ingested_ids=ingested_ids,
        )

        return report

    def compute_overlap_metrics(
        self,
        db_session: Session,
        sport: str,
        raw_pulled_count: int,
        valid_count: int,
        skipped_count: int,
        ingested_ids: Set[str],
    ) -> Dict[str, Any]:
        """
        Calculates overlap between newly ingested jarbet_history records and existing csv_backfill records:
        - Match by match_id
        - Match by natural key triplet (home_team, away_team, match_start_time)
        Also computes actual date range covered.
        """
        # Fetch all csv_backfill matches for this sport
        csv_query = select(Match.match_id, Match.home_team, Match.away_team, Match.match_start_time).where(
            Match.sport == sport, Match.source == "csv_backfill"
        )
        csv_rows = db_session.execute(csv_query).fetchall()

        csv_ids = {r[0] for r in csv_rows}
        csv_triplets = {(r[1].lower(), r[2].lower(), r[3]) for r in csv_rows}

        # Query all matches processed in this ingestion pass by ingested_ids
        history_query = select(Match.match_id, Match.home_team, Match.away_team, Match.match_start_time).where(
            Match.match_id.in_(ingested_ids)
        )
        history_rows = db_session.execute(history_query).fetchall()

        overlap_by_id = 0
        overlap_by_triplet = 0
        timestamps = []

        for m_id, h_team, a_team, start_time in history_rows:
            if m_id in csv_ids:
                overlap_by_id += 1
            if (h_team.lower(), a_team.lower(), start_time) in csv_triplets:
                overlap_by_triplet += 1
            if start_time:
                timestamps.append(start_time)

        min_date = min(timestamps).isoformat() if timestamps else None
        max_date = max(timestamps).isoformat() if timestamps else None

        new_records_count = len(history_rows) - max(overlap_by_id, overlap_by_triplet)

        report = {
            "sport": sport,
            "total_records_pulled": raw_pulled_count,
            "confirmed_result_records": valid_count,
            "skipped_incomplete_records": skipped_count,
            "total_ingested": len(history_rows),
            "overlap_with_csv_backfill_by_id": overlap_by_id,
            "overlap_with_csv_backfill_by_triplet": overlap_by_triplet,
            "genuinely_new_training_records": max(0, new_records_count),
            "date_range_start": min_date,
            "date_range_end": max_date,
        }

        return report

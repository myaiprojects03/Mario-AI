from typing import Dict, Any, List
import polars as pl


def compute_h2h_features(
    df: pl.DataFrame,
    entity_a_col: str = "home_player",
    entity_b_col: str = "away_player",
    time_col: str = "startedAt",
    score_a_col: str = "home.goals",
    score_b_col: str = "away.goals",
    prefix: str = "h2h",
) -> pl.DataFrame:
    """
    Computes generic head-to-head record summary between two entities (player/team pairings)
    strictly as of prior matches (excluding the match being featurized).
    Optimized to O(N) linear time using cumulative hash lookup tables.
    """
    if df.is_empty():
        return df

    sorted_df = df.sort(time_col)
    records = sorted_df.to_dicts()
    
    # Hash table tracking cumulative history per entity pair: (min_entity, max_entity) -> stats dict
    h2h_history: Dict[tuple, Dict[str, Any]] = {}
    results = []

    for current in records:
        curr_a = current.get(entity_a_col)
        curr_b = current.get(entity_b_col)
        
        if not curr_a or not curr_b:
            results.append({
                f"{prefix}_matches_count": 0,
                f"{prefix}_entity_a_wins": 0,
                f"{prefix}_entity_b_wins": 0,
                f"{prefix}_draws": 0,
                f"{prefix}_win_rate_a": 0.0,
                f"{prefix}_mean_score_diff": 0.0,
                f"{prefix}_mean_total_score": 0.0,
            })
            continue

        pair_key = (min(curr_a, curr_b), max(curr_a, curr_b))
        
        if pair_key not in h2h_history:
            h2h_history[pair_key] = {
                "matches": [],  # List of past (entity_a, score_a, score_b)
            }

        past_matches = h2h_history[pair_key]["matches"]
        count = len(past_matches)
        
        a_wins = 0
        b_wins = 0
        draws = 0
        total_diff = 0.0
        total_score_sum = 0.0

        for past_a, s_a, s_b in past_matches:
            # Normalize scores from perspective of current entity A
            if past_a == curr_a:
                eff_a, eff_b = s_a, s_b
            else:
                eff_a, eff_b = s_b, s_a

            if eff_a > eff_b:
                a_wins += 1
            elif eff_b > eff_a:
                b_wins += 1
            else:
                draws += 1

            total_diff += (eff_a - eff_b)
            total_score_sum += (eff_a + eff_b)

        win_rate = (a_wins / count) if count > 0 else 0.0
        mean_diff = (total_diff / count) if count > 0 else 0.0
        mean_total = (total_score_sum / count) if count > 0 else 0.0

        results.append({
            f"{prefix}_matches_count": count,
            f"{prefix}_entity_a_wins": a_wins,
            f"{prefix}_entity_b_wins": b_wins,
            f"{prefix}_draws": draws,
            f"{prefix}_win_rate_a": win_rate,
            f"{prefix}_mean_score_diff": mean_diff,
            f"{prefix}_mean_total_score": mean_total,
        })

        # Update history with current match's outcome after recording features (strictly past-only)
        s_a_val = current.get(score_a_col)
        s_b_val = current.get(score_b_col)
        if s_a_val is not None and s_b_val is not None:
            h2h_history[pair_key]["matches"].append((curr_a, float(s_a_val), float(s_b_val)))

    features_df = pl.DataFrame(results)
    return pl.concat([sorted_df, features_df], how="horizontal_extend")

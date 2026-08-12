import sys
import site
import pytest
from datetime import datetime, timedelta, timezone
import polars as pl

user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

from markets.fifa_goals_ou.features import build_fifa_goals_ou_features, FEATURE_COLUMNS
from markets.fifa_asian_handicap.features import build_fifa_asian_handicap_features, AH_FEATURE_COLUMNS


@pytest.fixture
def sample_fifa_matches():
    base_time = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    return pl.DataFrame({
        "match_id": ["m1", "m2", "m3", "m4", "m5"],
        "home_player": ["P_ALPHA", "P_ALPHA", "P_ALPHA", "P_ALPHA", "P_ALPHA"],
        "away_player": ["P_BETA", "P_BETA", "P_BETA", "P_BETA", "P_BETA"],
        "startedAt": [base_time + timedelta(hours=i) for i in range(5)],
        "home.goals": [3.0, 2.0, 4.0, 1.0, 5.0],
        "away.goals": [1.0, 2.0, 0.0, 2.0, 1.0],
        "home.goalsHT": [1.0, 1.0, 2.0, 0.0, 2.0],
        "league": ["Esoccer Battle"] * 5,
        "odds.over_under.line": [2.5, 2.5, 3.5, 3.5, 4.5],
        "odds.over_under.over": [1.85, 1.90, 1.80, 1.95, 1.85],
        "closingOdds.over_under.over": [1.90, 1.85, 1.95, 1.90, 1.80],
        "odds.asian_handicap.line": [-0.5, -0.5, -1.0, -1.0, -1.5],
    })


def test_hand_computed_example_verification(sample_fifa_matches):
    """
    HAND-COMPUTED EXAMPLE VERIFICATION:
    Verifies feature calculation against exact hand-calculated values for match #3 (m3).
    - Prior matches for P_ALPHA: m1 (scored 3, conceded 1) and m2 (scored 2, conceded 2).
    - Match m3 home_scored_roll_5: (3.0 + 2.0)/2 = 2.50
    - Match m3 away_scored_roll_5: (1.0 + 2.0)/2 = 1.50
    - Match m3 expected_total_goals: 2.50 + 1.50 = 4.00
    - Match m3 ou_line_value: 3.5
    - Match m3 ou_line_diff: 4.00 - 3.5 = 0.50
    - Match m3 odds_drift_abs: 1.95 - 1.80 = 0.15
    - Match m3 odds_drift_pct: (0.15 / 1.80) * 100 = 8.333%
    - Match m3 expected_home_margin: 2.50 - 1.50 = 1.00
    - Match m3 handicap_line_value: -1.0
    - Match m3 normalized_adjusted_margin: 1.00 + (-1.0) = 0.00
    """
    ou_df = build_fifa_goals_ou_features(sample_fifa_matches)
    ah_df = build_fifa_asian_handicap_features(sample_fifa_matches)

    m3_ou = ou_df.filter(pl.col("match_id") == "m3")
    m3_ah = ah_df.filter(pl.col("match_id") == "m3")

    # 1. Verification of O/U market features
    assert m3_ou["is_reliable_5"][0] == False  # only 2 prior matches exist
    assert m3_ou["expected_total_goals"][0] == pytest.approx(4.00)
    assert m3_ou["ou_line_value"][0] == pytest.approx(3.50)
    assert m3_ou["ou_line_diff"][0] == pytest.approx(0.50)
    assert m3_ou["odds_drift_abs"][0] == pytest.approx(0.15)
    assert m3_ou["odds_drift_pct"][0] == pytest.approx(8.333, rel=1e-3)

    # 2. Verification of Asian Handicap features
    assert m3_ah["expected_home_margin"][0] == pytest.approx(1.00)
    assert m3_ah["handicap_line_value"][0] == pytest.approx(-1.00)
    assert m3_ah["normalized_adjusted_margin"][0] == pytest.approx(0.00)

    # 3. Verification of match m4 (where 3 prior matches exist -> is_reliable becomes True)
    m4_ou = ou_df.filter(pl.col("match_id") == "m4")
    assert m4_ou["is_reliable_5"][0] == True  # m1, m2, m3 exist (3 prior matches)


def test_no_nan_leakage_and_report_nan_rates(sample_fifa_matches):
    """
    NO NAN LEAKAGE ASSERTION:
    Asserts that no NaN values leak through into feature vectors, reporting null rates per column.
    """
    ou_df = build_fifa_goals_ou_features(sample_fifa_matches)
    ah_df = build_fifa_asian_handicap_features(sample_fifa_matches)

    total_rows = len(sample_fifa_matches)

    print("\n--- O/U Feature Column Null Rates ---")
    for col in FEATURE_COLUMNS:
        null_cnt = ou_df[col].null_count()
        null_rate = (null_cnt / total_rows) * 100.0
        print(f"Column '{col}': {null_cnt} nulls ({null_rate:.2f}%)")
        assert null_cnt == 0, f"NaN/Null leakage detected in column '{col}'!"

    print("\n--- Asian Handicap Feature Column Null Rates ---")
    for col in AH_FEATURE_COLUMNS:
        null_cnt = ah_df[col].null_count()
        null_rate = (null_cnt / total_rows) * 100.0
        print(f"Column '{col}': {null_cnt} nulls ({null_rate:.2f}%)")
        assert null_cnt == 0, f"NaN/Null leakage detected in column '{col}'!"


def test_fifa_market_no_future_data_leakage(sample_fifa_matches):
    """
    DATA LEAKAGE PROOF TEST:
    Mutates future match m5's goals and closing odds, asserting earlier feature vectors (m1..m4) are 100% identical.
    """
    ou_orig = build_fifa_goals_ou_features(sample_fifa_matches)
    ah_orig = build_fifa_asian_handicap_features(sample_fifa_matches)

    # Mutate future match m5 goals from 5.0 to 99.0 and odds from 1.80 to 10.0
    mutated_matches = sample_fifa_matches.with_columns([
        pl.when(pl.col("match_id") == "m5").then(99.0).otherwise(pl.col("home.goals")).alias("home.goals"),
        pl.when(pl.col("match_id") == "m5").then(10.0).otherwise(pl.col("closingOdds.over_under.over")).alias("closingOdds.over_under.over"),
    ])

    ou_mut = build_fifa_goals_ou_features(mutated_matches)
    ah_mut = build_fifa_asian_handicap_features(mutated_matches)

    # Compare features for earlier matches m1..m4
    for mid in ["m1", "m2", "m3", "m4"]:
        orig_row_ou = ou_orig.filter(pl.col("match_id") == mid)
        mut_row_ou = ou_mut.filter(pl.col("match_id") == mid)

        for col in FEATURE_COLUMNS:
            val_o = orig_row_ou[col][0]
            val_m = mut_row_ou[col][0]
            assert val_o == val_m, f"Data leakage! Column '{col}' changed for match '{mid}' when mutating future match m5!"

        orig_row_ah = ah_orig.filter(pl.col("match_id") == mid)
        mut_row_ah = ah_mut.filter(pl.col("match_id") == mid)

        for col in AH_FEATURE_COLUMNS:
            val_o = orig_row_ah[col][0]
            val_m = mut_row_ah[col][0]
            assert val_o == val_m, f"Data leakage! Column '{col}' changed for match '{mid}' when mutating future match m5!"

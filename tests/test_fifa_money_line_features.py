import sys
import site
import pytest
from datetime import datetime, timedelta, timezone
import polars as pl

user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

from markets.fifa_money_line.features import build_fifa_money_line_features, ML_FEATURE_COLUMNS


@pytest.fixture
def sample_ml_matches():
    base_time = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    return pl.DataFrame({
        "match_id": ["m1", "m2", "m3", "m4", "m5"],
        "home_player": ["P_ALPHA", "P_ALPHA", "P_ALPHA", "P_ALPHA", "P_ALPHA"],
        "away_player": ["P_BETA", "P_BETA", "P_BETA", "P_BETA", "P_BETA"],
        "startedAt": [base_time + timedelta(hours=i) for i in range(5)],
        "home.goals": [3.0, 1.0, 2.0, 1.0, 0.0],
        "away.goals": [1.0, 1.0, 0.0, 4.0, 2.0],  # Outcomes for P_ALPHA: Win, Draw, Win, Loss, Loss
        "league": ["Esoccer Battle"] * 5,
        "odds.money_line.home": [1.80, 1.90, 1.85, 2.00, 2.10],
        "closingOdds.money_line.home": [1.85, 1.80, 1.90, 2.10, 2.00],
    })


def test_money_line_hand_computed_example_verification(sample_ml_matches):
    """
    HAND-COMPUTED EXAMPLE VERIFICATION FOR MONEY LINE:
    Match sequence for P_ALPHA:
    - m1: Win (3-1) -> past streak = 0
    - m2: Draw (1-1) -> past streak = +1
    - m3: Win (2-0) -> past streak = 0 (reset by draw)
    - m4: Loss (1-4) -> past streak = +1 (1 win before m4)
    - m5: Loss (0-2) -> past streak = -1 (1 loss before m5)

    Verification for match m4 (4th match):
    - Prior outcomes for P_ALPHA: m1(Win), m2(Draw), m3(Win) -> 2 Wins, 1 Draw out of 3 matches.
    - home_win_rate_roll_5: 2/3 = 0.66666
    - home_draw_rate_roll_5: 1/3 = 0.33333
    - home_loss_rate_roll_5: 0/3 = 0.00000
    - home_form_streak: +1
    - is_reliable_5: True (3 prior matches exist)
    """
    ml_df = build_fifa_money_line_features(sample_ml_matches)

    m4 = ml_df.filter(pl.col("match_id") == "m4")
    m5 = ml_df.filter(pl.col("match_id") == "m5")

    # Match m4 verification
    assert m4["is_reliable_5"][0] == True
    assert m4["home_win_rate_roll_5"][0] == pytest.approx(0.66666, rel=1e-3)
    assert m4["home_draw_rate_roll_5"][0] == pytest.approx(0.33333, rel=1e-3)
    assert m4["home_loss_rate_roll_5"][0] == pytest.approx(0.00000)
    assert m4["home_form_streak"][0] == 1

    # Match m5 verification (past outcomes m1..m4: Win, Draw, Win, Loss)
    assert m5["home_form_streak"][0] == -1  # match m4 was a Loss, so streak is -1


def test_money_line_no_nan_leakage_and_report_rates(sample_ml_matches):
    """
    ZERO NAN LEAKAGE ASSERTION:
    Asserts that no NaN values leak into Money Line feature vectors, reporting null rates per column.
    """
    ml_df = build_fifa_money_line_features(sample_ml_matches)
    total_rows = len(sample_ml_matches)

    print("\n--- Money Line Feature Column Null Rates ---")
    for col in ML_FEATURE_COLUMNS:
        null_cnt = ml_df[col].null_count()
        null_rate = (null_cnt / total_rows) * 100.0
        print(f"Column '{col}': {null_cnt} nulls ({null_rate:.2f}%)")
        assert null_cnt == 0, f"NaN/Null leakage detected in column '{col}'!"


def test_money_line_no_future_data_leakage(sample_ml_matches):
    """
    DATA LEAKAGE PROOF TEST:
    Mutates future match m5's goals and closing odds, asserting earlier feature vectors (m1..m4) are 100% identical.
    """
    ml_orig = build_fifa_money_line_features(sample_ml_matches)

    # Mutate future match m5 outcome from 0-2 to 10-0 (Win for home) and odds
    mutated_matches = sample_ml_matches.with_columns([
        pl.when(pl.col("match_id") == "m5").then(10.0).otherwise(pl.col("home.goals")).alias("home.goals"),
        pl.when(pl.col("match_id") == "m5").then(0.0).otherwise(pl.col("away.goals")).alias("away.goals"),
        pl.when(pl.col("match_id") == "m5").then(10.0).otherwise(pl.col("closingOdds.money_line.home")).alias("closingOdds.money_line.home"),
    ])

    ml_mut = build_fifa_money_line_features(mutated_matches)

    # Compare features for earlier matches m1..m4
    for mid in ["m1", "m2", "m3", "m4"]:
        orig_row = ml_orig.filter(pl.col("match_id") == mid)
        mut_row = ml_mut.filter(pl.col("match_id") == mid)

        for col in ML_FEATURE_COLUMNS:
            val_o = orig_row[col][0]
            val_m = mut_row[col][0]
            assert val_o == val_m, f"Data leakage! Column '{col}' changed for match '{mid}' when mutating future match m5!"

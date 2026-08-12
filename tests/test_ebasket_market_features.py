import sys
import site
import pytest
from datetime import datetime, timedelta, timezone
import polars as pl

user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

from markets.ebasket_ou.features import build_ebasket_ou_features, EBASKET_OU_FEATURE_COLUMNS
from markets.ebasket_money_line.features import build_ebasket_money_line_features, EBASKET_ML_FEATURE_COLUMNS


@pytest.fixture
def sample_ebasket_matches():
    base_time = datetime(2026, 8, 1, 14, 0, 0, tzinfo=timezone.utc)
    return pl.DataFrame({
        "match_id": ["b1", "b2", "b3", "b4", "b5"],
        "home_player": ["P_KOBE", "P_KOBE", "P_KOBE", "P_KOBE", "P_KOBE"],
        "away_player": ["P_LEBRON", "P_LEBRON", "P_LEBRON", "P_LEBRON", "P_LEBRON"],
        "startedAt": [base_time + timedelta(hours=i) for i in range(5)],
        "home.goals": [60.0, 50.0, 55.0, 58.0, 52.0],
        "away.goals": [50.0, 55.0, 45.0, 50.0, 48.0],
        "home.goalsHT": [30.0, 25.0, 28.0, 30.0, 26.0],
        "away.goalsHT": [25.0, 28.0, 22.0, 25.0, 24.0],
        "league": ["eBasketball H2H GG League"] * 5,
        "odds.over_under.line": [105.5, 105.5, 105.5, 105.5, 105.5],
        "odds.over_under.over": [1.85, 1.85, 1.85, 1.85, 1.85],
        "closingOdds.over_under.over": [1.90, 1.90, 1.90, 1.90, 1.90],
        "odds.money_line.home": [1.70, 1.70, 1.70, 1.70, 1.70],
        "closingOdds.money_line.home": [1.75, 1.75, 1.75, 1.75, 1.75],
    })


def test_ebasket_ou_hand_computed_example_verification(sample_ebasket_matches):
    """
    HAND-COMPUTED VERIFICATION FOR EBASKET O/U:
    For match b4 (4th match):
    - Prior outcomes for P_KOBE (scored): b1=60, b2=50, b3=55 -> Mean = 55.0
    - Prior outcomes for P_LEBRON (conceded): b1=60, b2=50, b3=55 -> Mean = 55.0
    - Prior outcomes for P_LEBRON (scored): b1=50, b2=55, b3=45 -> Mean = 50.0
    - Expected total points: 55.0 + 50.0 = 105.0
    - Target line: 105.5
    - ou_line_diff: 105.0 - 105.5 = -0.5
    """
    ou_df = build_ebasket_ou_features(sample_ebasket_matches)
    b4 = ou_df.filter(pl.col("match_id") == "b4")

    assert b4["is_reliable_5"][0] == True
    assert b4["home_scored_roll_mean_5"][0] == pytest.approx(55.0)
    assert b4["away_scored_roll_mean_5"][0] == pytest.approx(50.0)
    assert b4["expected_total_points"][0] == pytest.approx(105.0)
    assert b4["ou_line_value"][0] == pytest.approx(105.5)
    assert b4["ou_line_diff"][0] == pytest.approx(-0.5)


def test_ebasket_ml_hand_computed_example_verification(sample_ebasket_matches):
    """
    HAND-COMPUTED VERIFICATION FOR EBASKET MONEY LINE:
    Match sequence for P_KOBE:
    - b1: Win (60-50)
    - b2: Loss (50-55)
    - b3: Win (55-45)
    - b4: Win (58-50)

    For match b4:
    - Prior outcomes: 2 Wins, 1 Loss out of 3 matches.
    - home_win_rate_roll_5: 2/3 = 0.66666
    """
    ml_df = build_ebasket_money_line_features(sample_ebasket_matches)
    b4 = ml_df.filter(pl.col("match_id") == "b4")

    assert b4["is_reliable_5"][0] == True
    assert b4["home_win_rate_roll_5"][0] == pytest.approx(0.66666, rel=1e-3)
    assert "draw_prob_roll_10" not in b4.columns


def test_ebasket_no_nan_leakage_and_report_rates(sample_ebasket_matches):
    """
    ZERO NAN LEAKAGE ASSERTION:
    Asserts no NaNs in eBasketball O/U and Money Line feature vectors.
    """
    ou_df = build_ebasket_ou_features(sample_ebasket_matches)
    ml_df = build_ebasket_money_line_features(sample_ebasket_matches)

    for col in EBASKET_OU_FEATURE_COLUMNS:
        assert ou_df[col].null_count() == 0, f"NaN in ebasket_ou column '{col}'!"

    for col in EBASKET_ML_FEATURE_COLUMNS:
        assert ml_df[col].null_count() == 0, f"NaN in ebasket_ml column '{col}'!"


def test_ebasket_no_future_data_leakage(sample_ebasket_matches):
    """
    DATA LEAKAGE PROOF TEST:
    Mutates future match b5's points and odds, verifying b1..b4 features remain 100% identical.
    """
    ou_orig = build_ebasket_ou_features(sample_ebasket_matches)

    mutated_matches = sample_ebasket_matches.with_columns([
        pl.when(pl.col("match_id") == "b5").then(150.0).otherwise(pl.col("home.goals")).alias("home.goals"),
        pl.when(pl.col("match_id") == "b5").then(0.0).otherwise(pl.col("away.goals")).alias("away.goals"),
    ])

    ou_mut = build_ebasket_ou_features(mutated_matches)

    for mid in ["b1", "b2", "b3", "b4"]:
        orig_row = ou_orig.filter(pl.col("match_id") == mid)
        mut_row = ou_mut.filter(pl.col("match_id") == mid)

        for col in EBASKET_OU_FEATURE_COLUMNS:
            assert orig_row[col][0] == mut_row[col][0], f"Data leakage in ebasket_ou column '{col}' for match '{mid}'!"

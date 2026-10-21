import os
import sys
import json

# Ensure Mario AI Code root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.ingestion.jarbet_client import JarBetClient
from core.live_publisher import get_model_manager, evaluate_market_opportunity, EBASKET_ML_FEATURE_COLUMNS

def test_ebasket_ml_evaluation():
    print("=" * 70)
    print("   TESTING EBASKET MONEY LINE PIPELINE & MODEL ALIGNMENT")
    print("=" * 70)

    mgr = get_model_manager()
    bundle = mgr.models.get("ebasket_money_line")
    assert bundle is not None, "ebasket_money_line model bundle failed to load!"
    assert isinstance(bundle, dict), "ebasket_money_line must be a dictionary bundle!"
    assert bundle.get("model_version") == "v2.0.0-reevaluated", f"Expected v2.0.0-reevaluated, got {bundle.get('model_version')}"
    
    print(f"Model loaded: {bundle.get('market')} ({bundle.get('model_version')})")
    print(f"Feature version: {bundle.get('feature_version')}")
    print(f"Model object: {type(bundle.get('model'))}")
    print(f"Calibrator object: {type(bundle.get('calibrator'))}")
    print(f"Bundle features count: {len(bundle.get('feature_names', []))}")
    print(f"Pipeline features count: {len(EBASKET_ML_FEATURE_COLUMNS)}")
    assert len(bundle.get('feature_names', [])) == len(EBASKET_ML_FEATURE_COLUMNS) == 30, "Feature column count mismatch!"
    
    # Test on live upcoming ebasket match from JarBet API
    client = JarBetClient()
    pre_eb = client.get_ebasket_pre() or []
    print(f"\nLive upcoming eBasket matches returned by API: {len(pre_eb)}")
    
    evaluated_count = 0
    opps_found = 0
    for m in pre_eb:
        odds = m.get("odds", {}) if isinstance(m.get("odds"), dict) else {}
        ml = odds.get("money_line")
        if not ml or not isinstance(ml, dict):
            continue
        
        h_obj = m.get("home", {}) if isinstance(m.get("home"), dict) else {}
        a_obj = m.get("away", {}) if isinstance(m.get("away"), dict) else {}
        hp = h_obj.get("name") or h_obj.get("teamName") or ""
        ap = a_obj.get("name") or a_obj.get("teamName") or ""
        ht = h_obj.get("teamName") or h_obj.get("name") or "Home"
        at = a_obj.get("teamName") or a_obj.get("name") or "Away"
        
        opp = evaluate_market_opportunity(
            m_key="ebasket_money_line",
            match=m,
            odds_dict=odds,
            h_player=hp,
            a_player=ap,
            home_team=ht,
            away_team=at,
            min_odds=1.50,
            min_edge=0.02,
            client=client
        )
        evaluated_count += 1
        print(f"\nMatch #{evaluated_count}: {ht} ({hp}) vs {at} ({ap})")
        print(f"  Offered Odds: Home {ml.get('home')} | Away {ml.get('away')}")
        if opp:
            opps_found += 1
            print(f"  >>> QUALIFIED TIP: {opp['pick_str']} @ {opp['odds']} | Edge: {opp['edge_str']} (Prob: {opp['prob_str']})")
        else:
            print("  --- No Edge (Sub-threshold or negative expectancy - correctly skipped)")
            
        if evaluated_count >= 5:
            break
            
    print(f"\nEvaluation complete: {evaluated_count} live eBasket matches processed, {opps_found} tips found.")
    print("ALL TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_ebasket_ml_evaluation()

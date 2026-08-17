import sys
import site
import requests
import json

sys.path.insert(0, ".")
from core.config.settings import settings
from core.ingestion.jarbet_client import JarBetClient

def main():
    client = JarBetClient(
        base_url=settings.JARBET_BASE_URL or "https://data.jarvisbet.com.br",
        api_key=settings.JARBET_API_KEY,
    )

    url_fifa = f"{client.base_url}/history/pre"
    url_ebasket = f"{client.base_url}/history/ebasket/pre"
    headers = dict(client.session.headers)

    print("--- Testing GET /history/pre parameter combinations ---")
    param_tests = [
        {},
        {"homeName": "Bomb1to"},
        {"homeName": "Bomb1to", "page": 1, "limit": 10},
        {"homeName": "Bomb1to", "page": 2, "limit": 10},
        {"homeName": "Bomb1to", "offset": 10, "limit": 10},
        {"homeName": "Bomb1to", "startDate": "2026-01-01", "endDate": "2026-08-01"},
        {"homeName": "Bomb1to", "from": "2026-01-01", "to": "2026-08-01"},
        {"homeName": "Bomb1to", "date": "2026-05-21"},
    ]

    for p in param_tests:
        r = requests.get(url_fifa, headers=headers, params=p)
        print(f"\nParams: {p}")
        print(f"Status: {r.status_code}")
        print(f"Headers: {dict(r.headers)}")
        text_snip = r.text[:300]
        print(f"Body: {text_snip}")

    print("\n--- Inspecting single historical record structure ---")
    r_sample = requests.get(url_fifa, headers=headers, params={"homeName": "Bomb1to"})
    if r_sample.status_code == 200:
        data = r_sample.json()
        items = data.get("matches", data) if isinstance(data, dict) else data
        if isinstance(items, list) and len(items) > 0:
            print("Sample FIFA history record JSON:")
            print(json.dumps(items[0], indent=2))

    print("\n--- Inspecting single eBasketball historical record structure ---")
    r_eb = requests.get(url_ebasket, headers=headers, params={"homeName": "JD"})
    if r_eb.status_code == 200:
        data = r_eb.json()
        items = data.get("matches", data) if isinstance(data, dict) else data
        if isinstance(items, list) and len(items) > 0:
            print("Sample eBasketball history record JSON:")
            print(json.dumps(items[0], indent=2))

if __name__ == "__main__":
    main()

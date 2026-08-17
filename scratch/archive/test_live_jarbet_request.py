import sys
import site
import json
import requests

sys.path.insert(0, ".")
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.insert(0, user_site)

from core.config.settings import settings
from core.ingestion.jarbet_client import (
    JarBetClient,
    detect_odds_snapshot_behavior,
    analyze_half_time_odds_presence,
)


def main():
    print(f"JARBET_BASE_URL: {settings.JARBET_BASE_URL}")
    print(f"JARBET_API_KEY: {'[SET]' if settings.JARBET_API_KEY else '[MISSING]'}")

    client = JarBetClient(
        base_url=settings.JARBET_BASE_URL or "https://data.jarvisbet.com.br",
        api_key=settings.JARBET_API_KEY,
    )

    url = f"{client.base_url}/matches/pre"
    headers = dict(client.session.headers)

    print(f"\n--- Making Live Request to {url} ---")
    print(f"Headers sent: {list(headers.keys())}")

    try:
        resp = requests.get(url, headers=headers, timeout=15.0)
        print(f"\n--- LIVE RESPONSE RESULT ---")
        print(f"Status Code: {resp.status_code}")
        print(f"Response Headers: {dict(resp.headers)}")
        print(f"\nRaw Body Snippet (first 1000 chars):")
        print(resp.text[:1000])

        if resp.status_code == 200:
            try:
                data = resp.json()
                print(f"\nSuccessfully parsed JSON data!")
                if isinstance(data, dict):
                    matches = data.get("matches", [data])
                elif isinstance(data, list):
                    matches = data
                else:
                    matches = []

                print(f"Matches count in live payload: {len(matches)}")

                # Run telemetry functions on real live data
                if len(matches) > 1:
                    snap_res = detect_odds_snapshot_behavior(matches[0], matches[1])
                elif len(matches) == 1:
                    snap_res = detect_odds_snapshot_behavior(matches[0], matches[0])
                else:
                    snap_res = {"is_dynamic": False, "behavior_type": "No matches returned"}

                ht_res = analyze_half_time_odds_presence(matches)

                # Write actual FINDINGS.md
                findings_text = [
                    "# Empirical JarBet API Findings (Real Live Telemetry)",
                    "",
                    "## 1. Rate Limiting Telemetry",
                    f"- **Live Response Status**: {resp.status_code}",
                    f"- **Headers Received**: {dict(resp.headers)}",
                    f"- **Observed Rate-Limit Headers**: Remaining={resp.headers.get('X-RateLimit-Remaining')}, Limit={resp.headers.get('X-RateLimit-Limit')}, Retry-After={resp.headers.get('Retry-After')}",
                    "",
                    "## 2. Odds Snapshot Behavior (`core.odds_snapshots`)",
                    f"- **Dynamic Odds Updates Detected**: {snap_res.get('is_dynamic')}",
                    f"- **Behavior Classification**: {snap_res.get('behavior_type')}",
                    "",
                    "## 3. Half-Time Odds Presence Across Leagues",
                    f"```json",
                    json.dumps(ht_res, indent=2),
                    "```",
                ]

                with open("core/ingestion/FINDINGS.md", "w", encoding="utf-8") as f:
                    f.write("\n".join(findings_text) + "\n")

                print("Successfully updated core/ingestion/FINDINGS.md with real live telemetry!")

            except Exception as parse_err:
                print(f"Error parsing JSON: {parse_err}")

    except Exception as e:
        print(f"Request Exception: {e}")


if __name__ == "__main__":
    main()

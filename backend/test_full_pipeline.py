"""
End-to-end pipeline test.
Queries most recent alert from Supabase, runs RAG analysis, prints result.
"""

import json
import sys
import os

os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx

FASTAPI_URL = "http://localhost:8000"
TIMEOUT = 300


def main():
    print("=" * 70)
    print("  TRACK-WATCH -- Full Pipeline Test")
    print("=" * 70)

    print("\n[1/3] Health check")
    try:
        health = httpx.get(f"{FASTAPI_URL}/health", timeout=10).json()
        print(f"      Supabase : {'OK' if health['supabase_connected'] else 'FAIL'}")
        print(f"      Embedder : {'OK' if health['embedder_loaded'] else 'FAIL'}")
    except Exception as e:
        print(f"  Server not reachable: {e}")
        sys.exit(1)

    from dotenv import load_dotenv
    load_dotenv()

    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY", "")

    print("\n[2/3] Querying most recent alert from Supabase")
    try:
        resp = httpx.get(
            f"{SUPABASE_URL}/rest/v1/track_alerts",
            params={
                "select": "id,track_section,status,temperature_c,deflection_pct,distance_cm,timestamp",
                "order": "id.desc",
                "limit": "5",
            },
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
            },
            timeout=15,
        )
        resp.raise_for_status()
        alerts = resp.json()
    except Exception as e:
        print(f"  Supabase query failed: {e}")
        sys.exit(1)

    if not alerts:
        print("  No alerts in track_alerts table.")
        sys.exit(1)

    for a in alerts:
        print(f"      id={a['id']} section={a['track_section']} "
              f"status={a['status']} temp={a['temperature_c']}C")

    alert_id = alerts[0]["id"]
    print(f"\n      Selected alert id={alert_id} ({alerts[0]['status']})")

    analyze_url = f"{FASTAPI_URL}/api/alerts/{alert_id}/analyze"
    print(f"\n[3/3] POST {analyze_url}")
    print("      Waiting for RAG + LLM inference...\n")

    try:
        analysis_resp = httpx.post(analyze_url, timeout=TIMEOUT)
        analysis_resp.raise_for_status()
        result = analysis_resp.json()
    except httpx.TimeoutException:
        print("  Timed out after 5 min. Is Ollama running?")
        sys.exit(1)
    except Exception as e:
        print(f"  Analysis failed: {e}")
        sys.exit(1)

    print("=" * 70)
    print(f"  Alert ID         : {result['alert_id']}")
    print(f"  Matched Documents: {result['matched_documents']}")
    print("-" * 70)
    print(result["llm_analysis"])
    print("=" * 70)
    print("  PASSED")
    print("=" * 70)


if __name__ == "__main__":
    main()

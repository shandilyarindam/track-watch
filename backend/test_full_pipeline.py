"""
Track-Watch -- Full Pipeline End-to-End Test
=============================================
1. Queries the most recent alert from Supabase `track_alerts`.
2. POSTs to /api/alerts/{id}/analyze on the local FastAPI server.
3. Pretty-prints the RAG + LLM analysis output.
"""

import json
import sys
import os

# Force UTF-8 output on Windows
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx

FASTAPI_URL = "http://localhost:8000"
TIMEOUT = 300  # 5 min -- LLM generation can be slow on CPU


def main():
    print("=" * 70)
    print("  TRACK-WATCH -- Full RAG Pipeline Test")
    print("=" * 70)

    # -- Step 0: Health check --
    print("\n[1/3] Checking server health ...")
    try:
        health = httpx.get(f"{FASTAPI_URL}/health", timeout=10).json()
        print(f"      Status          : {health['status']}")
        print(f"      Supabase        : {'OK' if health['supabase_connected'] else 'FAIL'}")
        print(f"      Embedder        : {'OK' if health['embedder_loaded'] else 'FAIL'}")
    except Exception as e:
        print(f"  [FAIL] Server not reachable: {e}")
        sys.exit(1)

    # -- Step 1: Find the most recent alert ID --
    from dotenv import load_dotenv
    load_dotenv()

    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY", "")

    print("\n[2/3] Querying Supabase for the most recent alert ...")
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
        print(f"  [FAIL] Supabase query failed: {e}")
        sys.exit(1)

    if not alerts:
        print("  [FAIL] No alerts found in track_alerts table!")
        sys.exit(1)

    print(f"      Found {len(alerts)} recent alerts:")
    for a in alerts:
        print(f"        id={a['id']}  section={a['track_section']}  "
              f"status={a['status']}  temp={a['temperature_c']}C  "
              f"defl={a['deflection_pct']}%  dist={a['distance_cm']}cm")

    # Pick the most recent one
    alert_id = alerts[0]["id"]
    chosen = alerts[0]
    print(f"\n      >> Selected alert id={alert_id} ({chosen['status']}) for analysis")

    # -- Step 2: Fire the RAG analysis --
    analyze_url = f"{FASTAPI_URL}/api/alerts/{alert_id}/analyze"
    print(f"\n[3/3] POST {analyze_url}")
    print("      Waiting for RAG pipeline + LLM inference (this may take 1-3 min on CPU) ...\n")

    try:
        analysis_resp = httpx.post(analyze_url, timeout=TIMEOUT)
        analysis_resp.raise_for_status()
        result = analysis_resp.json()
    except httpx.TimeoutException:
        print("  [FAIL] Request timed out after 5 min. Is Ollama running with llama3.2:3b loaded?")
        sys.exit(1)
    except Exception as e:
        print(f"  [FAIL] Analysis request failed: {e}")
        sys.exit(1)

    # -- Pretty-print results --
    print("=" * 70)
    print("  ANALYSIS RESULT")
    print("=" * 70)
    print(f"  Alert ID         : {result['alert_id']}")
    print(f"  Matched Documents: {result['matched_documents']}")
    print(f"  Query Sent       : {result['query']}")
    print("-" * 70)
    print("  LLM MAINTENANCE ANALYSIS:")
    print("-" * 70)
    print(result["llm_analysis"])
    print("=" * 70)
    print("  [OK] Full pipeline test PASSED -- all stages executed successfully!")
    print("=" * 70)


if __name__ == "__main__":
    main()

"""
RAG pipeline verification.
Queries Supabase for most recent alert, hits /analyze, prints LLM output.
"""

import os
import sys

import httpx
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
API_BASE = "http://localhost:8000"


def main():
    print("=" * 70)
    print("  TRACK-WATCH -- RAG PIPELINE TEST")
    print("=" * 70)

    print("\n[1/4] Querying Supabase for recent alerts\n")
    sb = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    result = sb.table("track_alerts") \
        .select("id, packet_id, temperature_c, deflection_pct, distance_cm, status") \
        .order("id", desc=True) \
        .limit(5) \
        .execute()

    if not result.data:
        print("  No alerts found. Insert telemetry first.")
        sys.exit(1)

    print(f"  Found {len(result.data)} recent alert(s):\n")
    print(f"  {'ID':<6} {'PKT':<8} {'TEMP':>7} {'DEFL':>7} {'DIST':>7} {'STATUS'}")
    print(f"  {'-'*6} {'-'*8} {'-'*7} {'-'*7} {'-'*7} {'-'*10}")
    for row in result.data:
        print(
            f"  {row['id']:<6} {row['packet_id']:<8} "
            f"{row['temperature_c']:>6.1f}C {row['deflection_pct']:>6.1f}% "
            f"{row['distance_cm']:>6.1f}cm {row['status']}"
        )

    target_id = result.data[0]["id"]
    print(f"\n  Selected alert id={target_id}")

    analyze_url = f"{API_BASE}/api/alerts/{target_id}/analyze"
    print(f"\n[2/4] POST {analyze_url}")
    print("      This may take 30-90 seconds...\n")

    try:
        with httpx.Client(timeout=360.0) as client:
            response = client.post(analyze_url)
    except httpx.ConnectError:
        print("  Cannot connect to FastAPI. Run: python main.py")
        sys.exit(1)

    print(f"[3/4] HTTP {response.status_code}\n")

    if response.status_code != 200:
        print(f"  {response.text}")
        sys.exit(1)

    data = response.json()

    print(f"  Alert ID        : {data['alert_id']}")
    print(f"  Matched Vectors : {data['matched_documents']} chunks")

    print("\n" + "=" * 70)
    print("  [4/4] LLM MAINTENANCE ANALYSIS")
    print("=" * 70)
    print()
    print(data["llm_analysis"])
    print()
    print("=" * 70)
    print(f"  Telemetry -> Embedding -> {data['matched_documents']} Matches -> LLM -> Checklist")
    print("=" * 70)


if __name__ == "__main__":
    main()

"""
Track-Watch — End-to-End RAG Pipeline Verification Script
==========================================================
1. Queries Supabase for the most recent alert in track_alerts.
2. Hits POST /api/alerts/{id}/analyze on the local FastAPI server.
3. Pretty-prints the full LLM-generated maintenance checklist.
"""

import os
import sys
import json

import httpx
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
API_BASE = "http://localhost:8000"


def main():
    # ── Step 1: Find the most recent alerts in Supabase ──────────
    print("=" * 70)
    print("  TRACK-WATCH — RAG PIPELINE END-TO-END TEST")
    print("=" * 70)

    print("\n[1/4] Querying Supabase for recent alerts...\n")
    sb = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    result = sb.table("track_alerts") \
        .select("id, packet_id, temperature_c, deflection_pct, distance_cm, status") \
        .order("id", desc=True) \
        .limit(5) \
        .execute()

    if not result.data:
        print("  ERROR: No alerts found in track_alerts table!")
        print("  Insert test telemetry first via POST /api/telemetry")
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

    # Pick the most recent alert
    target_id = result.data[0]["id"]
    target = result.data[0]
    print(f"\n  -> Selected alert id={target_id} (most recent)")

    # ── Step 2: Hit the /analyze endpoint ────────────────────────
    analyze_url = f"{API_BASE}/api/alerts/{target_id}/analyze"
    print(f"\n[2/4] Sending POST to {analyze_url}")
    print("      (embedding query -> vector search -> Ollama LLM)")
    print("      This may take 30-90 seconds...\n")

    try:
        with httpx.Client(timeout=360.0) as client:
            response = client.post(analyze_url)
    except httpx.ConnectError:
        print("  ERROR: Cannot connect to FastAPI server!")
        print("  Ensure the server is running: python main.py")
        sys.exit(1)

    # ── Step 3: Parse response ───────────────────────────────────
    print(f"[3/4] Server responded: HTTP {response.status_code}\n")

    if response.status_code != 200:
        print(f"  ERROR: {response.text}")
        sys.exit(1)

    data = response.json()

    print(f"  Alert ID        : {data['alert_id']}")
    print(f"  Query Sent      : {data['query']}")
    print(f"  Matched Vectors : {data['matched_documents']} chunks from knowledge base")

    # ── Step 4: Print the LLM analysis ───────────────────────────
    print("\n" + "=" * 70)
    print("  [4/4] LLM MAINTENANCE ANALYSIS (llama3.2:3b via Ollama)")
    print("=" * 70)
    print()
    print(data["llm_analysis"])
    print()
    print("=" * 70)
    print("  RAG PIPELINE VERIFICATION: COMPLETE")
    print(f"  Telemetry -> Embedding -> {data['matched_documents']} Vector Matches -> LLM -> Checklist")
    print("=" * 70)


if __name__ == "__main__":
    main()

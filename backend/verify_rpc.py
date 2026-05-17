"""
Isolation test: Supabase connection + match_railway_knowledge RPC.
Generates a mock 384-dim vector and calls the RPC directly.

    python verify_rpc.py
"""

import os
import sys
import traceback

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")


def main():
    print("=" * 60)
    print("  VERIFY SUPABASE RPC: match_railway_knowledge")
    print("=" * 60)

    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        print("\n  FAIL: SUPABASE_URL or SUPABASE_ANON_KEY not set in .env")
        sys.exit(1)

    print(f"\n  URL : {SUPABASE_URL}")
    print(f"  KEY : {SUPABASE_ANON_KEY[:12]}...{SUPABASE_ANON_KEY[-4:]}")

    # 1. Connect
    print("\n[1/3] Creating Supabase client...")
    try:
        sb = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
        print("      OK")
    except Exception as e:
        print(f"      FAIL: {e}")
        traceback.print_exc()
        sys.exit(1)

    # 2. Verify table exists
    print("\n[2/3] Querying track_alerts (limit 1)...")
    try:
        r = sb.table("track_alerts").select("id, status").limit(1).execute()
        print(f"      OK -> {r.data}")
    except Exception as e:
        print(f"      FAIL: {e}")
        traceback.print_exc()

    # 3. Call RPC with mock vector
    print("\n[3/3] Calling RPC match_railway_knowledge with mock 384-dim vector...")
    mock_vector = [0.01] * 384
    try:
        rpc_result = sb.rpc(
            "match_railway_knowledge",
            {
                "query_embedding": mock_vector,
                "match_threshold": 0.0,
                "match_count": 3,
            },
        ).execute()
        print(f"      OK -> returned {len(rpc_result.data)} chunks")
        for i, chunk in enumerate(rpc_result.data or []):
            doc = chunk.get("document_name", "?")
            sec = chunk.get("section_title", "?")
            sim = chunk.get("similarity", 0)
            print(f"      [{i+1}] {doc} / {sec} (similarity={sim:.4f})")
    except Exception as e:
        print(f"      FAIL: {e}")
        print(f"\n      This likely means the Postgres function 'match_railway_knowledge'")
        print(f"      does not exist in your Supabase instance.")
        print(f"      Create it via Supabase SQL Editor.\n")
        traceback.print_exc()

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()

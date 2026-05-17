"""
Verify RAG pipeline for alert ID 16.
Falls back to health check if alert not found.
"""

import sys
import httpx

API_BASE = "http://localhost:8000"


def main():
    print("=" * 70)
    print("  TRACK-WATCH -- ALERT ANALYSIS VERIFICATION")
    print("=" * 70)

    target_id = 16

    print(f"\nAnalyzing alert ID {target_id}...")
    print(f"  POST {API_BASE}/api/alerts/{target_id}/analyze")
    print(f"  May take 30-90s (RAG pipeline with Ollama)")

    try:
        with httpx.Client(timeout=300.0) as client:
            response = client.post(f"{API_BASE}/api/alerts/{target_id}/analyze")

            if response.status_code == 404:
                print(f"  Alert ID {target_id} not found (404)")
                health = client.get(f"{API_BASE}/health").json()
                print(f"  Server health: {health}")
                sys.exit(1)

            elif response.status_code == 200:
                data = response.json()
                print_results(data)
            else:
                print(f"  Unexpected: {response.status_code}")
                print(f"  {response.text}")
                sys.exit(1)

    except httpx.ConnectError:
        print(f"  Cannot connect to {API_BASE}")
        print(f"  Run: uvicorn main:app --host 0.0.0.0 --port 8000")
        sys.exit(1)


def print_results(data):
    print("\n" + "=" * 70)
    print(f"  Alert ID        : {data['alert_id']}")
    print(f"  Query           : {data['query']}")
    print(f"  Matched Docs    : {data['matched_documents']}")
    print("\n" + "-" * 70)
    print(data["llm_analysis"])
    print("=" * 70)
    print("  VERIFICATION: PASSED")
    print("=" * 70)


if __name__ == "__main__":
    main()

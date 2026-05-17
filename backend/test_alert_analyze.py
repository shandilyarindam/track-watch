"""
Test script to verify RAG pipeline for alert analysis.
1. Try alert ID 16 first via API
2. If 404, try to find most recent CAUTION/CRITICAL alert via API health check
3. Execute POST /api/alerts/{id}/analyze
4. Print the LLM response
"""

import os
import sys
import json

import httpx

API_BASE = "http://localhost:8000"


def main():
    print("=" * 70)
    print("  TRACK-WATCH — ALERT ANALYSIS RAG VERIFICATION")
    print("=" * 70)
    
    target_id = 16
    
    # Step 1: Try alert ID 16 first via the API
    print("\n[Step 1] Testing alert ID 16 via API...")
    analyze_url = f"{API_BASE}/api/alerts/{target_id}/analyze"
    print(f"  URL: {analyze_url}")
    print(f"  NOTE: This may take 30-90 seconds (RAG pipeline with Ollama)")
    
    try:
        with httpx.Client(timeout=300.0) as client:
            response = client.post(analyze_url)
            
        if response.status_code == 404:
            print(f"  [NOT FOUND] Alert ID 16 not found (404)")
            print(f"  [INFO] Checking if FastAPI server is healthy...")
            
            # Check server health
            health_response = client.get(f"{API_BASE}/health")
            if health_response.status_code == 200:
                health_data = health_response.json()
                print(f"  [OK] Server is healthy: {health_data}")
                print(f"  [INFO] Alert ID 16 doesn't exist in the database.")
                print(f"  [ACTION] Please insert test telemetry first or provide a valid alert ID.")
                sys.exit(1)
            else:
                print(f"  [ERROR] Server health check failed: {health_response.status_code}")
                sys.exit(1)
                
        elif response.status_code == 200:
            print(f"  [OK] Alert ID 16 found and analyzed successfully!")
            data = response.json()
            print_results(data)
            return
        else:
            print(f"  [ERROR] Unexpected status code: {response.status_code}")
            print(f"  Response: {response.text}")
            sys.exit(1)
            
    except httpx.ConnectError:
        print(f"  [ERROR] Cannot connect to FastAPI server at {API_BASE}")
        print(f"  [ACTION] Ensure the server is running: uvicorn main:app --host 0.0.0.0 --port 8000")
        sys.exit(1)
    except Exception as e:
        print(f"  [ERROR] Request failed: {e}")
        sys.exit(1)


def print_results(data):
    print("\n" + "=" * 70)
    print("  RESPONSE METADATA")
    print("=" * 70)
    print(f"  Alert ID           : {data['alert_id']}")
    print(f"  Query Text         : {data['query']}")
    print(f"  Matched Documents  : {data['matched_documents']}")
    
    print("\n" + "=" * 70)
    print("  LLM MAINTENANCE ANALYSIS (llama3.2:3b via Ollama)")
    print("=" * 70)
    print()
    print(data["llm_analysis"])
    print()
    print("=" * 70)
    print("  RAG PIPELINE VERIFICATION: SUCCESS")
    print("=" * 70)


if __name__ == "__main__":
    main()

"""
Track-Watch Backend

    POST /api/telemetry           — ingest from ESP32-S3 fog node
    POST /api/alerts/{id}/analyze — RAG: embed, vector search, LLM
    GET  /api/alerts              — list recent alerts
    GET  /health                  — liveness probe

    uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import logging
import os
import textwrap
import traceback
from datetime import datetime, timezone
from typing import Optional

import json

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
EMBEDDING_MODEL: str = os.getenv(
    "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("track-watch")

supabase_client: Client | None = None
embedder: SentenceTransformer | None = None

app = FastAPI(
    title="Track-Watch API",
    description="Railway Track Health Monitoring",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event() -> None:
    global supabase_client, embedder

    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        logger.error("SUPABASE_URL and SUPABASE_ANON_KEY must be set.")
        raise RuntimeError("Missing Supabase credentials.")

    supabase_client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    logger.info("Supabase client initialised -> %s", SUPABASE_URL)

    logger.info("Loading embedding model: %s", EMBEDDING_MODEL)
    embedder = SentenceTransformer(EMBEDDING_MODEL)
    logger.info("Embedding model loaded -> dim=%d", embedder.get_sentence_embedding_dimension())


class TelemetryPayload(BaseModel):
    packet_id: int = Field(..., description="Monotonic counter from fog node.")
    track_section: str = Field(default="KM-42-DELHI")
    temperature_c: float = Field(...)
    deflection_pct: float = Field(...)
    distance_cm: float = Field(...)
    status: str = Field(default="NOMINAL")
    timestamp: Optional[str] = Field(default=None)

    class Config:
        json_schema_extra = {
            "example": {
                "packet_id": 1024,
                "track_section": "KM-42-DELHI",
                "temperature_c": 32.4,
                "deflection_pct": 12.5,
                "distance_cm": 31.8,
                "status": "NOMINAL",
            }
        }


class TelemetryResponse(BaseModel):
    message: str
    record_id: Optional[int] = None


@app.post(
    "/api/telemetry",
    response_model=TelemetryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest telemetry from fog node",
    tags=["Telemetry"],
)
async def ingest_telemetry(payload: TelemetryPayload) -> TelemetryResponse:
    """Accepts a telemetry packet, validates, inserts into track_alerts."""
    if supabase_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase client not initialised.",
        )

    record = payload.model_dump()
    if record["timestamp"] is None:
        record["timestamp"] = datetime.now(timezone.utc).isoformat()

    logger.info(
        "Ingesting packet #%d | section=%s status=%s temp=%.1fC defl=%.1f%% dist=%.1fcm",
        record["packet_id"],
        record["track_section"],
        record["status"],
        record["temperature_c"],
        record["deflection_pct"],
        record["distance_cm"],
    )

    try:
        result = (
            supabase_client.table("track_alerts")
            .insert(record)
            .execute()
        )
        inserted = result.data
        record_id = inserted[0]["id"] if inserted else None
        logger.info("Inserted record id=%s", record_id)
        return TelemetryResponse(
            message="Telemetry ingested successfully.", record_id=record_id
        )
    except Exception as exc:
        logger.exception("Failed to insert telemetry.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database insertion failed: {exc}",
        ) from exc


class AlertListItem(BaseModel):
    id: int
    packet_id: int
    track_section: str
    temperature_c: float
    deflection_pct: float
    distance_cm: float
    status: str
    timestamp: str


class AlertsResponse(BaseModel):
    alerts: list[AlertListItem]
    count: int


@app.get(
    "/api/alerts",
    response_model=AlertsResponse,
    summary="List recent track alerts",
    tags=["Telemetry"],
)
async def list_alerts(limit: int = 20) -> AlertsResponse:
    """Most recent alerts, ordered by ID descending."""
    if supabase_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase client not initialised.",
        )

    logger.info("Fetching recent alerts (limit=%d)", limit)

    try:
        result = (
            supabase_client.table("track_alerts")
            .select("*")
            .order("id", desc=True)
            .limit(limit)
            .execute()
        )
        alerts_data = result.data or []
        logger.info("Retrieved %d alerts.", len(alerts_data))
        return AlertsResponse(alerts=alerts_data, count=len(alerts_data))
    except Exception as exc:
        logger.exception("Failed to fetch alerts.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database query failed: {exc}",
        ) from exc


@app.post(
    "/api/alerts/{alert_id}/analyze",
    summary="Streaming RAG analysis of a specific alert",
    tags=["Analysis"],
)
async def analyze_alert(alert_id: int):
    """Fetch alert -> embed -> vector search -> stream Ollama tokens.

    Response format (text/event-stream, one JSON object per line):
      Line 1:  {"type":"meta", "alert_id":N, "query":"...", "matched_documents":N}
      Line 2+: {"type":"token", "text":"..."}
      Last:    {"type":"done"}
      Error:   {"type":"error", "detail":"..."}
    """
    if supabase_client is None or embedder is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Backend services not ready.",
        )

    # --- Pre-LLM pipeline (runs before streaming starts) ---

    logger.info("Analyzing alert id=%d", alert_id)
    try:
        result = (
            supabase_client.table("track_alerts")
            .select("*")
            .eq("id", alert_id)
            .execute()
        )
    except Exception as exc:
        print(f"RAG_ERROR [FETCH_ALERT]: {exc}")
        traceback.print_exc()
        logger.exception("Failed to fetch alert id=%d.", alert_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database query failed: {exc}",
        ) from exc

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert id={alert_id} not found.",
        )

    alert = result.data[0]
    logger.info(
        "Fetched alert -> section=%s status=%s temp=%.1fC",
        alert["track_section"],
        alert["status"],
        alert["temperature_c"],
    )

    query_text = (
        f"Railway track alert on section {alert['track_section']}. "
        f"Status: {alert['status']}. "
        f"Temperature: {alert['temperature_c']}C. "
        f"Deflection: {alert['deflection_pct']}%. "
        f"Distance clearance: {alert['distance_cm']} cm. "
        f"What maintenance actions are recommended for these readings?"
    )
    logger.info("Query text: %s", query_text)

    try:
        query_embedding: list[float] = embedder.encode(query_text).tolist()
    except Exception as exc:
        print(f"RAG_ERROR [EMBEDDING]: {exc}")
        traceback.print_exc()
        logger.exception("Embedding generation failed.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Embedding error: {exc}",
        ) from exc

    try:
        rpc_result = supabase_client.rpc(
            "match_railway_knowledge",
            {
                "query_embedding": query_embedding,
                "match_threshold": 0.3,
                "match_count": 3,
            },
        ).execute()
        matched_chunks = rpc_result.data or []
    except Exception as exc:
        print(f"RAG_ERROR [VECTOR_SEARCH_RPC]: {exc}")
        traceback.print_exc()
        logger.exception("Vector search RPC failed.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Vector search failed: {exc}",
        ) from exc

    matched_count = len(matched_chunks)
    logger.info("Vector search returned %d chunks.", matched_count)

    context_blocks: list[str] = []
    for idx, chunk in enumerate(matched_chunks, 1):
        doc_name = chunk.get("document_name", "Unknown")
        section = chunk.get("section_title", "")
        content = chunk.get("content", "")
        similarity = chunk.get("similarity", 0.0)
        context_blocks.append(
            f"[Source {idx}] {doc_name} -- {section} (similarity: {similarity:.3f})\n{content}"
        )

    context_str = "\n\n---\n\n".join(context_blocks) if context_blocks else "No relevant documents found."

    system_prompt = textwrap.dedent("""\
        You are Track-Watch AI, a senior railway maintenance advisor.
        You are given live telemetry from an IoT-monitored track section
        and relevant excerpts from Indian Railways maintenance manuals.

        Your response MUST be a concise, actionable maintenance checklist
        formatted for a field engineer. Include:
        1. Severity assessment (NOMINAL / CAUTION / CRITICAL)
        2. Root cause hypothesis based on the sensor readings
        3. Immediate actions (numbered steps)
        4. Follow-up inspections required
        5. Relevant RDSO circular references (if found in context)

        Be specific. Reference actual sensor values. Do NOT hallucinate
        standards or circulars not present in the provided context.
    """)

    user_prompt = textwrap.dedent(f"""\
        ## Alert Telemetry
        - Track Section: {alert['track_section']}
        - Status: {alert['status']}
        - Temperature: {alert['temperature_c']}C
        - Deflection: {alert['deflection_pct']}%
        - Distance Clearance: {alert['distance_cm']} cm
        - Timestamp: {alert.get('timestamp', 'N/A')}

        ## Retrieved Knowledge Base Context
        {context_str}

        Provide your maintenance analysis and checklist below:
    """)

    ollama_url = f"{OLLAMA_BASE_URL}/api/generate"

    # --- Streaming generator ---

    async def stream_generator():
        # Emit metadata header
        yield json.dumps({
            "type": "meta",
            "alert_id": alert_id,
            "query": query_text,
            "matched_documents": matched_count,
        }) + "\n"

        try:
            logger.info("Streaming Ollama at %s model=%s", ollama_url, OLLAMA_MODEL)
            async with httpx.AsyncClient(timeout=600.0) as client:
                async with client.stream(
                    "POST",
                    ollama_url,
                    json={
                        "model": OLLAMA_MODEL,
                        "prompt": user_prompt,
                        "system": system_prompt,
                        "stream": True,
                        "options": {
                            "temperature": 0.4,
                            "num_predict": 1024,
                        },
                    },
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        token = chunk.get("response", "")
                        if token:
                            yield json.dumps({"type": "token", "text": token}) + "\n"
                        if chunk.get("done", False):
                            break

            yield json.dumps({"type": "done"}) + "\n"
            logger.info("Streaming complete for alert id=%d", alert_id)

        except httpx.TimeoutException as exc:
            print(f"RAG_ERROR [OLLAMA_TIMEOUT]: {exc}")
            traceback.print_exc()
            logger.error("Ollama stream timed out.")
            yield json.dumps({"type": "error", "detail": "LLM timed out. Is Ollama running?"}) + "\n"
        except httpx.HTTPStatusError as exc:
            print(f"RAG_ERROR [OLLAMA_HTTP]: {exc.response.status_code}")
            traceback.print_exc()
            logger.exception("Ollama HTTP error during stream.")
            yield json.dumps({"type": "error", "detail": f"Ollama HTTP {exc.response.status_code}"}) + "\n"
        except Exception as exc:
            print(f"RAG_ERROR [OLLAMA_STREAM]: {exc}")
            traceback.print_exc()
            logger.exception("Ollama stream failed.")
            yield json.dumps({"type": "error", "detail": f"LLM error: {exc}"}) + "\n"

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/health", tags=["System"])
async def health_check():
    return {
        "status": "healthy",
        "service": "Track-Watch API",
        "supabase_connected": supabase_client is not None,
        "embedder_loaded": embedder is not None,
    }


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting Track-Watch API server")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )

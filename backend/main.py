"""
Track-Watch Backend — FastAPI Server
=====================================
Enterprise-grade real-time Railway Track Health Monitoring System.

Endpoints:
    POST /api/telemetry           — Ingest telemetry from ESP32-S3 fog node.
    POST /api/alerts/{id}/analyze — RAG pipeline: embed → vector search → LLM analysis.

Run:
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import logging
import os
import textwrap
from datetime import datetime, timezone
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer
from supabase import create_client, Client

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
load_dotenv()

SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
EMBEDDING_MODEL: str = os.getenv(
    "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("track-watch")

# ──────────────────────────────────────────────
# Globals (lazy-initialised at startup)
# ──────────────────────────────────────────────
supabase_client: Client | None = None
embedder: SentenceTransformer | None = None

# ──────────────────────────────────────────────
# FastAPI App
# ──────────────────────────────────────────────
app = FastAPI(
    title="Track-Watch API",
    description="Railway Track Health Monitoring — Telemetry Ingestion & RAG Analysis",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
# Startup / Shutdown
# ──────────────────────────────────────────────
@app.on_event("startup")
async def startup_event() -> None:
    """Initialise Supabase client and download / cache the embedding model."""
    global supabase_client, embedder

    # --- Supabase ---
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        logger.error(
            "SUPABASE_URL and SUPABASE_ANON_KEY must be set in the environment."
        )
        raise RuntimeError("Missing Supabase credentials — check .env file.")

    supabase_client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    logger.info("Supabase client initialised  →  %s", SUPABASE_URL)

    # --- Embedding model ---
    logger.info("Loading embedding model: %s …", EMBEDDING_MODEL)
    embedder = SentenceTransformer(EMBEDDING_MODEL)
    logger.info(
        "Embedding model loaded  →  dim=%d", embedder.get_sentence_embedding_dimension()
    )


# ══════════════════════════════════════════════
# 1.  POST /api/telemetry
# ══════════════════════════════════════════════

class TelemetryPayload(BaseModel):
    """Pydantic model matching the `track_alerts` Supabase schema."""

    packet_id: int = Field(..., description="Monotonically increasing packet counter from the fog node.")
    track_section: str = Field(default="KM-42-DELHI", description="Track section identifier.")
    temperature_c: float = Field(..., description="LM35 temperature reading in °C.")
    deflection_pct: float = Field(..., description="Flex-sensor derived deflection percentage.")
    distance_cm: float = Field(..., description="HC-SR04 ultrasonic distance in cm.")
    status: str = Field(
        default="NOMINAL",
        description="Edge-evaluated status: NOMINAL | CAUTION | CRITICAL.",
    )
    timestamp: Optional[str] = Field(
        default=None,
        description="ISO-8601 timestamp. Auto-generated if omitted.",
    )

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
    summary="Ingest telemetry from the ESP32-S3 fog node",
    tags=["Telemetry"],
)
async def ingest_telemetry(payload: TelemetryPayload) -> TelemetryResponse:
    """
    Accepts a single telemetry packet from the fog node,
    validates it against the Pydantic model, and inserts it
    into the ``track_alerts`` table in Supabase.
    """
    if supabase_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase client not initialised.",
        )

    # Auto-generate timestamp if not provided
    record = payload.model_dump()
    if record["timestamp"] is None:
        record["timestamp"] = datetime.now(timezone.utc).isoformat()

    logger.info(
        "Ingesting packet #%d  |  section=%s  status=%s  temp=%.1f°C  defl=%.1f%%  dist=%.1fcm",
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
        logger.info("Inserted record id=%s into track_alerts.", record_id)
        return TelemetryResponse(
            message="Telemetry ingested successfully.", record_id=record_id
        )

    except Exception as exc:
        logger.exception("Failed to insert telemetry into Supabase.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database insertion failed: {exc}",
        ) from exc


# ══════════════════════════════════════════════
# 2.  GET /api/alerts
# ══════════════════════════════════════════════

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
    """
    Retrieve the most recent telemetry alerts from the ``track_alerts`` table.
    Results are ordered by ID descending (most recent first).
    """
    if supabase_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase client not initialised.",
        )

    logger.info("Fetching recent alerts (limit=%d)...", limit)

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


# ══════════════════════════════════════════════
# 3.  POST /api/alerts/{alert_id}/analyze
# ══════════════════════════════════════════════

class AnalysisResponse(BaseModel):
    alert_id: int
    query: str
    matched_documents: int
    llm_analysis: str


@app.post(
    "/api/alerts/{alert_id}/analyze",
    response_model=AnalysisResponse,
    summary="RAG analysis of a specific alert",
    tags=["Analysis"],
)
async def analyze_alert(alert_id: int) -> AnalysisResponse:
    """
    Full RAG pipeline for a single alert:
        1. Fetch alert row from ``track_alerts``.
        2. Build a natural-language query from telemetry values.
        3. Embed the query using sentence-transformers (384-dim).
        4. Vector-search ``railway_knowledge_base`` via the
           ``match_railway_knowledge`` RPC function.
        5. Compile top-3 context chunks → prompt Ollama (llama3.2:3b).
        6. Return the structured maintenance checklist.
    """
    if supabase_client is None or embedder is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Backend services not ready.",
        )

    # ── Step 1: Fetch the alert row ──────────────────────────
    logger.info("Analyzing alert id=%d …", alert_id)
    try:
        result = (
            supabase_client.table("track_alerts")
            .select("*")
            .eq("id", alert_id)
            .execute()
        )
    except Exception as exc:
        logger.exception("Failed to fetch alert id=%d.", alert_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database query failed: {exc}",
        ) from exc

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert id={alert_id} not found in track_alerts.",
        )

    alert = result.data[0]
    logger.info(
        "Fetched alert → section=%s  status=%s  temp=%.1f°C",
        alert["track_section"],
        alert["status"],
        alert["temperature_c"],
    )

    # ── Step 2: Build textual query ──────────────────────────
    query_text = (
        f"Railway track alert on section {alert['track_section']}. "
        f"Status: {alert['status']}. "
        f"Temperature: {alert['temperature_c']}°C. "
        f"Deflection: {alert['deflection_pct']}%. "
        f"Distance clearance: {alert['distance_cm']} cm. "
        f"What maintenance actions are recommended for these readings?"
    )
    logger.info("Query text: %s", query_text)

    # ── Step 3: Generate 384-dim embedding ───────────────────
    try:
        query_embedding: list[float] = embedder.encode(query_text).tolist()
    except Exception as exc:
        logger.exception("Embedding generation failed.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Embedding error: {exc}",
        ) from exc

    # ── Step 4: Vector search via Supabase RPC ───────────────
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
        logger.exception("Vector search RPC failed.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Vector search failed: {exc}",
        ) from exc

    matched_count = len(matched_chunks)
    logger.info("Vector search returned %d matching chunks.", matched_count)

    # ── Step 5: Build context and LLM prompt ─────────────────
    context_blocks: list[str] = []
    for idx, chunk in enumerate(matched_chunks, 1):
        doc_name = chunk.get("document_name", "Unknown")
        section = chunk.get("section_title", "")
        content = chunk.get("content", "")
        similarity = chunk.get("similarity", 0.0)
        context_blocks.append(
            f"[Source {idx}] {doc_name} — {section} (similarity: {similarity:.3f})\n{content}"
        )

    context_str = "\n\n---\n\n".join(context_blocks) if context_blocks else "No relevant documents found."

    system_prompt = textwrap.dedent("""\
        You are Track-Watch AI, a senior railway maintenance advisor.
        You are given real-time telemetry from an IoT-monitored track section
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
        - Temperature: {alert['temperature_c']}°C
        - Deflection: {alert['deflection_pct']}%
        - Distance Clearance: {alert['distance_cm']} cm
        - Timestamp: {alert.get('timestamp', 'N/A')}

        ## Retrieved Knowledge Base Context
        {context_str}

        Provide your maintenance analysis and checklist below:
    """)

    # ── Step 6: Call Ollama LLM ──────────────────────────────
    llm_response_text = ""
    ollama_url = f"{OLLAMA_BASE_URL}/api/generate"

    try:
        logger.info("Calling Ollama at %s  model=%s …", ollama_url, OLLAMA_MODEL)
        async with httpx.AsyncClient(timeout=300.0) as client:
            ollama_response = await client.post(
                ollama_url,
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": user_prompt,
                    "system": system_prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.4,
                        "num_predict": 1024,
                    },
                },
            )
            ollama_response.raise_for_status()
            llm_response_text = ollama_response.json().get("response", "")

    except httpx.TimeoutException:
        logger.error("Ollama request timed out after 120s.")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="LLM analysis timed out. Ensure Ollama is running and the model is loaded.",
        )
    except httpx.HTTPStatusError as exc:
        logger.exception("Ollama returned an HTTP error.")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ollama error: {exc.response.status_code} — {exc.response.text}",
        ) from exc
    except Exception as exc:
        logger.exception("Ollama communication failed.")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM service unavailable: {exc}",
        ) from exc

    logger.info(
        "LLM analysis complete  →  %d chars returned.", len(llm_response_text)
    )

    return AnalysisResponse(
        alert_id=alert_id,
        query=query_text,
        matched_documents=matched_count,
        llm_analysis=llm_response_text,
    )


# ──────────────────────────────────────────────
# Health Check
# ──────────────────────────────────────────────
@app.get("/health", tags=["System"])
async def health_check():
    """Lightweight liveness probe."""
    return {
        "status": "healthy",
        "service": "Track-Watch API",
        "supabase_connected": supabase_client is not None,
        "embedder_loaded": embedder is not None,
    }


# ──────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    logger.info("Starting Track-Watch API server …")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )

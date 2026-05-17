# Track-Watch

An edge-to-cloud railway track structural safety monitoring and automated regulatory compliance validation system.

Telemetry data is sampled from physical instrumentation sensors via a standalone edge node, transmitted using layer-2 ESP-NOW protocols to a dual-core gateway, pushed upstream via HTTP POST to a FastAPI application gateway, and persisted in a Supabase PostgreSQL instance. A localized Retrieval-Augmented Generation (RAG) engine transforms structural anomalies into dense text tensors via all-MiniLM-L6-v2, queries adjacent regulatory safety circulars via pgvector similarity matching, and triggers an asynchronous NDJSON token stream from a local Ollama Llama 3.2 3B daemon to render audit-compliant engineering checklists.

### Dependencies

* Python 3.13
* Ollama (Llama 3.2 3B Engine)
* Supabase PostgreSQL (with pgvector extension)
* Arduino IDE (with ESP32/ESP32-S3 core toolchains)

### Setup

1. Initialize local database schema tables via Supabase SQL Editor using the data model matrices defined in `ARCHITECTURE.md`.

2. Install pinned backend dependencies:
   ```bash
   pip install -r backend/requirements.txt
   ```

3. Configure local environment variables:
   ```bash
   cp backend/.env.example backend/.env
   ```

4. Populate knowledge directories and execute vector store ingestion seeder:
   ```bash
   python backend/ingest_docs.py
   ```

5. Compile and flash firmware binaries to microcontrollers over native serial interfaces:
   ```
   Compile hardware/sensor-node/sensor-node.ino -> Target: ESP32 Dev Module
   Compile hardware/fog-node/fog-node.ino -> Target: ESP32-S3 Dev Module
   ```

6. Initialize local AI inference engine daemon:
   ```bash
   ollama run llama3.2:3b
   ```

7. Launch core FastAPI backend application server:
   ```bash
   python backend/main.py
   ```

8. Launch the dashboard interface by opening `dashboard/index.html` in a standard browser environment.

### Architecture

```mermaid
sequenceDiagram
    autonumber
    participant S as Sensor Node (ESP32)
    participant G as Fog Gateway (ESP32-S3)
    participant API as Core API (FastAPI)
    participant DB as Vector DB (Supabase)
    participant LLM as Local LLM (Ollama)

    note over S,G: ESP-NOW Protocol (Channel 11 Layer 2)
    S->>G: Broadcast Raw Telemetry Packet Frame
    alt FreeRTOS Queue Push Success
        G->>G: Core 0: Intercept packet, push to thread-safe internal queue
    else Queue Overflow / Buffer Collision
        G->>G: Drop frame, increment hardware packet loss tracking register
    end
    G->>API: Core 1: Dequeue, switch radio state, HTTP POST /api/telemetry
    alt Ingestion Pathway Validated
        API->>DB: Insert transactional record into track_alerts table
        API-->>G: HTTP 201 Created
    else Schema Validation Failure
        API-->>G: HTTP 422 Unprocessable Entity
    end

    note over API,LLM: Asynchronous NDJSON RAG Execution Loop
    API->>DB: RPC match_railway_knowledge() (Cosine Distance Metrics)
    DB-->>API: Return top 3 matched RDSO manual text blocks
    API->>LLM: Stream context-grounded system prompt (stream=true)
    loop Token-by-Token Tokenization
        LLM-->>API: Yield incremental markdown text token strings
        API-->>G: Pipe streaming chunk line ({"type":"token", "text":"..."})
    end
```

### Known Limitations

* Prototype edge firmware lacks payload-layer transport encryption over raw ESP-NOW broadcasts.
* Fixed client-side polling interval increases connection overhead under high client concurrency.
* Local vector tensor calculations block execution threads if hardware environment lacks active GPU acceleration.

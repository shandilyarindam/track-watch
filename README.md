# Track-Watch: Dual-Core Edge-to-Cloud RAG Architecture for Railway Safety Monitoring

A production-grade railway track health monitoring system combining dual-core ESP32-S3 fog computing, real-time telemetry ingestion, and grounded AI-powered maintenance recommendations using Retrieval-Augmented Generation (RAG).

## Overview

Track-Watch is a 4-tier edge-to-cloud architecture that enables real-time railway track monitoring with AI-driven maintenance planning. The system captures telemetry from IoT sensors, processes it at the fog layer using dual-core ESP32-S3, stores data in Supabase, and generates grounded maintenance recommendations using local LLM inference with RDSO safety manual context.

### Architecture Tiers

1. **Edge Layer** - ESP32-S3 sensor nodes with ESP-NOW protocol for loss-tolerant telemetry
2. **Fog Layer** - Dual-core ESP32-S3 gateway with FreeRTOS inter-core queue communication
3. **Cloud Gateway** - FastAPI backend with Supabase PostgreSQL + pgvector
4. **Local RAG Engine** - SentenceTransformers embeddings + Ollama llama3.2:3b for grounded analysis

---

## Hardware Prerequisites

### Sensor Nodes (Edge Layer)
- **Microcontroller**: ESP32-S3 (WiFi + Bluetooth 5.0)
- **Temperature Sensor**: LM35 analog temperature sensor
- **Flex Sensor**: Conductive polymer flex sensor for track deflection measurement
- **Distance Sensor**: HC-SR04 ultrasonic sensor for track clearance monitoring
- **Power**: 3.7V Li-ion battery with solar charging option

### Fog Gateway (Aggregation Node)
- **Microcontroller**: ESP32-S3 dual-core (Xtensa LX7 dual-core, 240MHz)
- **Connectivity**: ESP-NOW receiver + WiFi client (2.4GHz)
- **Storage**: SPIFFS for local buffering during network outages
- **Power**: 5V USB-C or external power supply

### Hardware Setup Notes
- **ESP-NOW Channel**: All devices must be synchronized to Channel 11 for reliable communication
- **Antenna**: Use external PCB antenna for improved range (up to 100m line-of-sight)
- **Sensor Calibration**: Calibrate flex sensor baseline and ultrasonic distance thresholds before deployment

---

## System Requirements

### Backend (Local Development)
- **Python**: 3.13 or higher
- **Operating System**: Windows, macOS, or Linux
- **Ollama**: Installed and running locally (llama3.2:3b model)
- **Supabase**: Account with PostgreSQL database + pgvector extension

### Python Dependencies
```bash
fastapi
uvicorn
supabase
sentence-transformers
python-dotenv
httpx
```

---

## Setup Guide

### 1. Hardware Flashing

#### Sensor Node Firmware
```bash
# Clone the firmware repository
git clone <firmware-repo>
cd firmware/sensor-node

# Configure ESP-NOW Channel 11
# Edit config.h:
#define ESPNOW_CHANNEL 11

# Flash to ESP32-S3
esptool.py --chip esp32s3 --port COM3 --baud 460800 \
  write_flash --flash_mode dio --flash_size 4MB \
  0x0 sensor_node.bin
```

#### Fog Gateway Firmware
```bash
cd firmware/fog-gateway

# Configure WiFi credentials and ESP-NOW Channel 11
# Edit config.h:
#define WIFI_SSID "your-network"
#define WIFI_PASSWORD "your-password"
#define ESPNOW_CHANNEL 11
#define API_ENDPOINT "http://your-backend-ip:8000/api/telemetry"

# Flash to ESP32-S3
esptool.py --chip esp32s3 --port COM4 --baud 460800 \
  write_flash --flash_mode dio --flash_size 4MB \
  0x0 fog_gateway.bin
```

### 2. Backend Setup

#### Clone Repository
```bash
git clone https://github.com/your-username/track-watch.git
cd track-watch
```

#### Install Python Dependencies
```bash
cd backend
pip install -r requirements.txt
```

#### Configure Environment Variables
```bash
cp .env.example .env
# Edit .env with your credentials:
# SUPABASE_URL=your-supabase-url
# SUPABASE_ANON_KEY=your-supabase-anon-key
# OLLAMA_BASE_URL=http://localhost:11434
# OLLAMA_MODEL=llama3.2:3b
# EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
```

#### Initialize Ollama
```bash
# Install Ollama (if not already installed)
# Visit: https://ollama.ai/download

# Pull the required model
ollama pull llama3.2:3b
```

#### Seed Knowledge Base
```bash
# Ingest RDSO track safety manuals into vector database
python ingest_docs.py
```

#### Start FastAPI Server
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Frontend Dashboard

#### Serve Dashboard
```bash
# Option 1: Simple HTTP server
cd dashboard
python -m http.server 3000

# Option 2: Use VS Code Live Server extension
# Right-click index.html -> Open with Live Server
```

#### Access Dashboard
Open browser to: `http://localhost:3000`

---

## Usage

### Live Telemetry Monitoring

1. **Power on sensor nodes** - They will begin transmitting telemetry via ESP-NOW
2. **Fog gateway receives packets** - Core 0 handles interrupts, queues data for Core 1
3. **Backend ingestion** - Fog node POSTs to `http://localhost:8000/api/telemetry`
4. **Dashboard updates** - Frontend polls `GET /api/alerts` for real-time stream

### Human-Led Compliance Audit

The system provides a complete audit trail for regulatory compliance:

#### 1. Alert Selection
- Click any alert card in the dashboard to open the detailed side panel
- View raw telemetry metrics (temperature, deflection, distance, timestamp)

#### 2. RAG Analysis Trigger
- Click **"Analyze Alert with RAG Pipeline"** button
- System executes:
  - Telemetry retrieval from Supabase
  - SentenceTransformers embedding generation (384-dim)
  - Vector similarity search against RDSO knowledge base
  - Context-aware prompt construction
  - Ollama llama3.2:3b inference (30-90 seconds)

#### 3. Audit Panel Display
- **Raw Telemetry Metrics**: Original sensor readings with timestamps
- **Seeded Reference Context**: Exact knowledge base chunks used for grounding (with similarity scores)
- **Grounded Maintenance Action Plan**: LLM-generated checklist citing specific RDSO circulars and standards

#### 4. Compliance Documentation
- Each analysis is logged with alert ID, timestamp, and matched document references
- Maintenance actions can be cross-referenced with triggering sensor values
- Full traceability from sensor reading to regulatory citation

---

## API Endpoints

### Telemetry Ingestion
```http
POST /api/telemetry
Content-Type: application/json

{
  "packet_id": 1024,
  "track_section": "KM-42-DELHI",
  "temperature_c": 32.4,
  "deflection_pct": 12.5,
  "distance_cm": 31.8,
  "status": "CAUTION",
  "timestamp": "2026-05-17T09:30:00.000Z"
}
```

### List Recent Alerts
```http
GET /api/alerts?limit=20
```

### RAG Analysis
```http
POST /api/alerts/{id}/analyze
```

### Health Check
```http
GET /health
```

---

## Database Schema

### track_alerts Table
| Column | Type | Description |
|--------|------|-------------|
| id | integer | Primary key, auto-increment |
| packet_id | integer | Monotonic counter from fog node |
| track_section | string | Track section identifier |
| temperature_c | float | Temperature in Celsius |
| deflection_pct | float | Deflection percentage |
| distance_cm | float | Distance in cm |
| status | string | NOMINAL/CAUTION/CRITICAL |
| timestamp | timestamp | ISO-8601 UTC timestamp |

### railway_knowledge_base Table
| Column | Type | Description |
|--------|------|-------------|
| id | integer | Primary key |
| document_name | string | Source document name |
| section_title | string | Section heading |
| content | text | Chunk content |
| embedding | vector(384) | SentenceTransformers embedding |

---

## Architecture Documentation

For detailed system architecture, data contracts, and sequence diagrams, see:
- [ARCHITECTURE.md](ARCHITECTURE.md) - Complete system documentation with Mermaid diagrams

---

## Troubleshooting

### ESP-NOW Communication Issues
- Verify all devices are on Channel 11
- Check antenna connections and line-of-sight clearance
- Monitor serial output for packet loss statistics

### Backend Connection Errors
- Confirm FastAPI server is running on port 8000
- Verify .env file has correct Supabase credentials
- Check Ollama service: `ollama list`

### RAG Analysis Timeouts
- Ensure llama3.2:3b model is loaded: `ollama run llama3.2:3b`
- Check system resources (minimum 8GB RAM recommended)
- Verify pgvector extension is enabled in Supabase

---

## Performance Characteristics

| Metric | Target | Notes |
|--------|--------|-------|
| Sensor sampling rate | 1-10 Hz | Configurable per node |
| ESP-NOW latency | < 5 ms | Line-of-sight, < 100m |
| Fog-to-cloud latency | 100-500 ms | Dependent on WiFi |
| Vector search latency | < 100 ms | pgvector index |
| LLM inference latency | 30-90 s | llama3.2:3b, 1024 tokens |
| End-to-end analysis | < 2 min | Alert to maintenance plan |

---

## Security Considerations

- **ESP-NOW**: No encryption by default; add application-layer encryption for production
- **WiFi**: Use WPA3-Enterprise for fog node authentication
- **API**: Implement API key authentication for frontend access
- **Supabase**: Enable Row-Level Security (RLS) policies
- **Ollama**: Bind to localhost only; no external exposure
- **HTTPS**: Use reverse proxy (nginx/caddy) for production TLS

---

## Future Enhancements

- Real-time WebSocket subscriptions for live dashboard updates
- Multi-section support with hierarchical monitoring
- Mobile push notifications for CRITICAL alerts
- Historical trend analysis and predictive maintenance
- Model fine-tuning on railway-specific corpus
- Edge ML with TensorFlow Lite Micro for on-device anomaly detection

---

## License

MIT License - See LICENSE file for details

---

## Authors

**Arindam Shandilya / !ordinary**  
Contact: shandilyarindam@gmail.com

---

## Acknowledgments

- RDSO (Research Designs and Standards Organisation) for track safety manuals
- Ollama for local LLM inference capabilities
- Supabase for managed PostgreSQL with pgvector
- Espressif for ESP32-S3 dual-core architecture

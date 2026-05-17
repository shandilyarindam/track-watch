"""
Ingest RDSO maintenance manuals into the RAG knowledge base.

    python ingest_docs.py
    python ingest_docs.py --docs-dir ./my_manuals
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")
EMBEDDING_MODEL: str = os.getenv(
    "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
KNOWLEDGE_DOCS_DIR: str = os.getenv("KNOWLEDGE_DOCS_DIR", "./knowledge_docs")

CHUNK_SIZE: int = 500
CHUNK_OVERLAP: int = 50
BATCH_SIZE: int = 25

SUPPORTED_EXTENSIONS: set[str] = {".txt", ".md"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("track-watch.ingest")


def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    chunks: list[str] = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = start + chunk_size

        if end < text_len:
            last_newline = text.rfind("\n", start, end)
            last_period = text.rfind(". ", start, end)
            break_point = max(last_newline, last_period)

            if break_point > start:
                end = break_point + 1

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        step = max(1, (end - start) - overlap)
        start += step

    return chunks


def extract_section_title(chunk: str) -> str:
    first_line = chunk.split("\n", 1)[0].strip()

    if first_line.startswith("#"):
        return first_line.lstrip("#").strip()

    # ALL-CAPS headings common in RDSO circulars
    if first_line.isupper() and len(first_line) < 120:
        return first_line

    return first_line[:60] + ("..." if len(first_line) > 60 else "")


def run_ingestion(docs_dir: str) -> None:
    docs_path = Path(docs_dir).resolve()

    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        logger.error("SUPABASE_URL and SUPABASE_ANON_KEY must be set.")
        sys.exit(1)

    if not docs_path.is_dir():
        logger.error("Documents directory not found: %s", docs_path)
        sys.exit(1)

    doc_files = sorted(
        f
        for f in docs_path.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    if not doc_files:
        logger.warning("No .txt or .md files found in %s", docs_path)
        sys.exit(0)

    logger.info("Found %d document(s) in %s", len(doc_files), docs_path)

    logger.info("Connecting to Supabase -> %s", SUPABASE_URL)
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

    logger.info("Loading embedding model: %s", EMBEDDING_MODEL)
    embedder = SentenceTransformer(EMBEDDING_MODEL)
    embedding_dim = embedder.get_sentence_embedding_dimension()
    logger.info("Embedding model ready -> dim=%d", embedding_dim)

    total_chunks_inserted = 0

    for doc_file in doc_files:
        doc_name = doc_file.name
        logger.info("Processing: %s", doc_name)

        try:
            raw_text = doc_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            logger.warning("Skipping %s -- could not decode as UTF-8.", doc_name)
            continue

        if not raw_text.strip():
            logger.warning("Skipping %s -- file is empty.", doc_name)
            continue

        chunks = chunk_text(raw_text)
        logger.info("  Chunked into %d blocks (size=%d, overlap=%d)", len(chunks), CHUNK_SIZE, CHUNK_OVERLAP)

        logger.info("  Generating embeddings")
        try:
            embeddings = embedder.encode(chunks, show_progress_bar=True, batch_size=32)
        except Exception as exc:
            logger.exception("  Embedding failed for %s -- skipping.", doc_name)
            continue

        rows: list[dict] = []
        for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            section_title = extract_section_title(chunk)
            rows.append(
                {
                    "document_name": doc_name,
                    "section_title": section_title,
                    "content": chunk,
                    "embedding": embedding.tolist(),
                }
            )

        logger.info("  Inserting %d rows into railway_knowledge_base", len(rows))
        inserted_count = 0

        for batch_start in range(0, len(rows), BATCH_SIZE):
            batch = rows[batch_start : batch_start + BATCH_SIZE]
            try:
                result = (
                    supabase.table("railway_knowledge_base")
                    .insert(batch)
                    .execute()
                )
                inserted_count += len(result.data) if result.data else 0
            except Exception as exc:
                logger.error("  Batch insert failed at offset %d: %s", batch_start, exc)

        logger.info("  Inserted %d / %d chunks for %s", inserted_count, len(rows), doc_name)
        total_chunks_inserted += inserted_count

    logger.info(
        "Ingestion complete. Total chunks: %d across %d document(s).",
        total_chunks_inserted,
        len(doc_files),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingest documents into Track-Watch RAG knowledge base.",
    )
    parser.add_argument(
        "--docs-dir",
        type=str,
        default=KNOWLEDGE_DOCS_DIR,
        help=f"Path to document directory (default: {KNOWLEDGE_DOCS_DIR})",
    )
    args = parser.parse_args()
    run_ingestion(args.docs_dir)

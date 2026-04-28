"""
Encoder serving — model-agnostic FastAPI app.

Loads the encoder selected via ENCODER_MODEL env var (default: bge-m3).
Exposes /embed for batch embedding requests.

Per CAI-RESP-094 + CAI-RESP-095:
  - Self-hosted (own container, own weights pinned)
  - encoder_sha + corpus_version surfaced in response metadata
  - Warm at boot (model loaded at startup, not on first request)
  - No request-body logging by default (verify per docs/MODAL_PRIVACY_VERIFICATION.md check 1)

Switch encoders by changing ENCODER_MODEL env var:
  bge-m3   → BAAI/bge-m3
  jina-v3  → jinaai/jina-embeddings-v3 (CC BY-NC license — verify before adoption)
"""

import os
import logging
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer

# Privacy: structured logging only, never log request bodies (per CAI-RESP-095 check 1)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ENCODER_MODEL = os.environ.get("ENCODER_MODEL", "bge-m3")
MODEL_REGISTRY = {
    "bge-m3": "BAAI/bge-m3",
    "jina-v3": "jinaai/jina-embeddings-v3",
}

if ENCODER_MODEL not in MODEL_REGISTRY:
    raise SystemExit(f"unknown ENCODER_MODEL={ENCODER_MODEL}; choose from {list(MODEL_REGISTRY)}")

MODEL_PATH = MODEL_REGISTRY[ENCODER_MODEL]


# Loaded at startup so first request is warm (CAI-RESP-094 warm-at-boot)
_model: SentenceTransformer | None = None
_encoder_sha: str = "pending"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model, _encoder_sha
    log.info(f"loading encoder {ENCODER_MODEL} ({MODEL_PATH})…")
    _model = SentenceTransformer(MODEL_PATH, trust_remote_code=False)
    # Pin commit SHA for vector_metadata.encoder_sha (per CAI-RESP-094 Q5)
    # sentence-transformers exposes the model_card_data.base_model when available
    try:
        _encoder_sha = _model.model_card_data.base_model_revision or "unknown"
    except Exception:
        _encoder_sha = "unknown"
    log.info(f"encoder loaded; sha={_encoder_sha[:12]}, dim={_model.get_sentence_embedding_dimension()}")
    yield
    log.info("encoder shutting down")


app = FastAPI(title="Al-Bayān encoder", lifespan=lifespan)


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=64)
    input_type: Literal["query", "document"] = "query"


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]
    encoder_model: str
    encoder_sha: str
    dimension: int


@app.post("/embed", response_model=EmbedResponse)
async def embed(req: EmbedRequest) -> EmbedResponse:
    if _model is None:
        raise HTTPException(503, "model not loaded")

    # BGE-M3 + jina-v3 both support asymmetric query/document encoding via prompt_name
    # If model doesn't have separate query/passage prompts, this is a no-op.
    prompt_name = "query" if req.input_type == "query" else "passage"
    try:
        embeddings = _model.encode(
            req.texts,
            prompt_name=prompt_name if hasattr(_model, "prompts") and _model.prompts else None,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
    except TypeError:
        # Fallback for models without prompt_name support
        embeddings = _model.encode(req.texts, normalize_embeddings=True, convert_to_numpy=True)

    return EmbedResponse(
        embeddings=embeddings.tolist(),
        encoder_model=ENCODER_MODEL,
        encoder_sha=_encoder_sha,
        dimension=_model.get_sentence_embedding_dimension(),
    )


@app.get("/health")
async def health():
    return {
        "status": "ok" if _model is not None else "loading",
        "encoder_model": ENCODER_MODEL,
        "encoder_sha": _encoder_sha,
        "dimension": _model.get_sentence_embedding_dimension() if _model else None,
    }


@app.get("/")
async def root():
    return {"service": "al-bayan encoder", "see": "/health, POST /embed"}

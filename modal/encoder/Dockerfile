# Encoder serving container — model-agnostic skeleton.
# Per CAI-RESP-094 (self-host) + CAI-RESP-095 (Modal-first for v0.2).
#
# Build:
#   docker build -t embedder.al-bayan modal/encoder/
#
# Modal deploys via modal_app.py — this Dockerfile defines the image base.

FROM python:3.11-slim

# Per CAI-RESP-095 CHECK 5 + CAI-RESP-103 + CAI-RESP-107: weights baked into
# image at build time (NOT pulled into a Modal Volume at runtime). Eliminates
# the read-write-Volume ambiguity entirely; encoder weights become part of
# container SHA → audit trail tightens, version-pin exact, cold-start improves.
# ENCODER_MODEL build-arg lets us produce per-encoder image variants
# (bge-m3 default; jina-v3 if it wins ENCODER-EVAL).
ARG ENCODER_MODEL=bge-m3

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ENCODER_MODEL=${ENCODER_MODEL} \
    HF_HOME=/opt/hf-cache

# Install build essentials for any compiled deps; clean apt lists to keep image lean
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# Pre-pull encoder weights at build time per CHECK 5. Adds ~2.3GB to image
# (BGE-M3) but eliminates first-cold-start HF download + Volume mount entirely.
# HF_HOME pinned to /opt/hf-cache (image-immutable layer, NOT a Modal Volume).
RUN python -c "import os; from sentence_transformers import SentenceTransformer; \
    registry = {'bge-m3': 'BAAI/bge-m3', 'jina-v3': 'jinaai/jina-embeddings-v3'}; \
    model_path = registry[os.environ['ENCODER_MODEL']]; \
    SentenceTransformer(model_path, trust_remote_code=False)"

COPY serve.py .

# At Modal cold-start: serve.py lifespan loads weights from /opt/hf-cache
# (already populated above). No HF download, no Volume mount, no race.
EXPOSE 8000
CMD ["uvicorn", "serve:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

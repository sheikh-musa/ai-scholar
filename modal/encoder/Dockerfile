# Encoder serving container — model-agnostic skeleton.
# Per CAI-RESP-094 (self-host) + CAI-RESP-095 (Modal-first for v0.2).
#
# Build:
#   docker build -t embedder.al-bayan modal/encoder/
#
# Modal deploys via modal_app.py — this Dockerfile defines the image base.

FROM python:3.11-slim

# Avoid prompts + reduce layer size
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/cache/hf

# Install build essentials for any compiled deps; clean apt lists to keep image lean
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY serve.py .

# At Modal cold-start: model_warm() pre-loads the encoder so first user
# query doesn't pay the model-load cost (per CAI-RESP-094 constraint
# "encoder MUST warm at orchestrator boot")
EXPOSE 8000
CMD ["uvicorn", "serve:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

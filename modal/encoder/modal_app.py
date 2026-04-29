"""
Modal app definition for the Al-Bayān encoder.

Per CAI-RESP-095 (A): Modal-first for v0.2 (Mac Mini → v0.2.5 milestone).
Auto-scales to zero when idle. Container weights pinned by us; same image
later swaps to local MLX runtime in v0.2.5 without app-code changes.

Deploy:
  modal deploy modal/encoder/modal_app.py

After deploy:
  - endpoint: https://<workspace>--al-bayan-encoder-fastapi-app.modal.run
  - GET /health to verify model loaded
  - POST /embed with {"texts": [...], "input_type": "query|document"}

Privacy posture (per docs/MODAL_PRIVACY_VERIFICATION.md):
  - region: REGION env var; pin to ap-southeast (Singapore + Indonesia user base)
  - logs: serve.py logs structured-only, never request bodies
  - secrets: ENCODER_MODEL only (no API keys in container)

Cost: serverless idle = $0; per-request ~$0.0001 (tiny CPU containers).
GPU swap-in only if ENCODER-EVAL winner benefits — BGE-M3 / jina-v3 both
fine on CPU at our throughput (~100 queries/min peak).
"""

import modal

# Per CAI-RESP-095: encoder warmed at boot, scale-to-zero, no warm-pool retention
app = modal.App("al-bayan-encoder")

# Image built from local Dockerfile in this same directory
image = (
    modal.Image.from_dockerfile(path="modal/encoder/Dockerfile", add_python="3.11")
    # ENCODER_MODEL set at Dockerfile build-time via ARG; HF_HOME pinned to
    # /opt/hf-cache (image-immutable). No env override needed at deploy time.
    # To swap encoders, rebuild image with --build-arg ENCODER_MODEL=jina-v3.
)


@app.function(
    image=image,
    # No Volume mount — weights baked into image per CAI-RESP-095 CHECK 5
    # + CAI-RESP-107. Container is fully self-contained; no read-write volume
    # for query state, no read-write volume for weights cache.
    region="ap-southeast",  # data residency per CAI-RESP-095 check 3 — pin to APAC
    timeout=120,             # per request; embedding is fast, this is generous
    container_idle_timeout=300,  # scale-to-zero after 5 min idle
    keep_warm=0,             # no warm-pool retention — per CAI-RESP-095 check 5
    cpu=2.0,
    memory=8192,             # BGE-M3 base ~2GB; jina-v3 ~2GB; headroom for batching
)
@modal.asgi_app()
def fastapi_app():
    from serve import app as fastapi_instance
    return fastapi_instance

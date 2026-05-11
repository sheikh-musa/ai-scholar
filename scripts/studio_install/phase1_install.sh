#!/usr/bin/env bash
# Phase 1 install for EMBED-PIPELINE-LOCAL-MAC-STUDIO-001 (id 814) +
# ENRICH-PIPELINE-LOCAL-MAC-STUDIO-001 (id 872). Run on Mac Studio.
#
# Substrate-verified 2026-05-08T15:38Z + retry 2026-05-08T16:11Z:
#   M2 Max 32GB, macOS 14.6, Tailscale 100.104.36.27, Xcode CLT.
#   /opt/homebrew owned by 'nisa' not 'musa' — brew install fails for musa.
#   Pivoted to uv (astral.sh) which downloads prebuilt Python distributions
#   without sudo, no source compile, no shared-prefix permission issues.
#
# Idempotent — re-running skips installed steps.

set -euo pipefail

TAILSCALE_IP="100.104.36.27"
SERVICE_ROOT="${HOME}/ai-scholar-services"
ENCODER_PORT=8080
LLM_PORT=8081
PYTHON_VER="3.12"
UV_BIN="${HOME}/.local/bin/uv"

log() { printf "\n[%s] %s\n" "$(date -u +%H:%M:%S)" "$*"; }

# --- Step 1: install uv (no sudo, no brew dep) ---
log "Step 1: install uv"
if [[ ! -x "${UV_BIN}" ]]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="${HOME}/.local/bin:${PATH}"
uv --version

# --- Step 2: install Python 3.12 via uv (prebuilt distribution) ---
log "Step 2: install Python ${PYTHON_VER}"
uv python install "${PYTHON_VER}"
PY_BIN="$(uv python find ${PYTHON_VER})"
"${PY_BIN}" --version

# --- Step 3: service root + venv ---
log "Step 3: ${SERVICE_ROOT} + venv"
mkdir -p "${SERVICE_ROOT}"
cd "${SERVICE_ROOT}"
[[ -d venv ]] || uv venv venv --python "${PY_BIN}"
# shellcheck disable=SC1091
source venv/bin/activate

# --- Step 4: deps via uv pip (fast) ---
log "Step 4: pip install deps"
uv pip install \
  "mlx-lm>=0.21.0" \
  "sentence-transformers>=3.0.0" \
  "fastapi>=0.115.0" \
  "uvicorn[standard]>=0.32.0" \
  "huggingface-hub>=0.26.0" \
  "torch>=2.4.0"

# --- Step 5: pull encoder weights (bge-m3 ~2.3GB) ---
log "Step 5: pull BAAI/bge-m3 encoder weights"
python - <<'PY'
from sentence_transformers import SentenceTransformer
m = SentenceTransformer("BAAI/bge-m3")
print(f"loaded bge-m3 dim={m.get_sentence_embedding_dimension()}")
PY

# --- Step 6: pull LLM weights (Gemma primary + Qwen alt for A/B) ---
# Q5_K_M is GGUF nomenclature (llama.cpp); MLX uses 4bit/8bit/QAT-variants.
# Substrate-verified mlx-community 2026-05-10: Gemma QAT-4bit is highest-usage
# (63K dl, Google's quantization-aware training, ~14GB); Qwen Instruct-4bit
# is the analogous pick (~18GB). Both fit alongside bge-m3 (~2GB) in 32GB RAM.
log "Step 6: pull mlx-community Gemma 3 27B QAT-4bit + Qwen 2.5 32B Instruct-4bit"
python - <<'PY'
from huggingface_hub import snapshot_download
import time
for repo in ("mlx-community/gemma-3-27b-it-qat-4bit",
             "mlx-community/Qwen2.5-32B-Instruct-4bit"):
    t0 = time.time()
    print(f"  downloading {repo} ...", flush=True)
    path = snapshot_download(repo_id=repo)
    print(f"  done {repo} -> {path} ({time.time()-t0:.0f}s)", flush=True)
PY

# --- Step 7: encoder service module ---
log "Step 7: write encoder_service.py (port ${ENCODER_PORT})"
cat > "${SERVICE_ROOT}/encoder_service.py" <<'PY'
from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
import uvicorn, os

app = FastAPI()
model = SentenceTransformer("BAAI/bge-m3")

class EmbedRequest(BaseModel):
    inputs: list[str]

@app.post("/embed")
def embed(req: EmbedRequest):
    vecs = model.encode(req.inputs, normalize_embeddings=True).tolist()
    return {"embeddings": vecs, "dim": len(vecs[0]) if vecs else 0}

@app.get("/health")
def health():
    return {"status": "ok", "model": "BAAI/bge-m3", "dim": model.get_sentence_embedding_dimension()}

if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("BIND_HOST", "127.0.0.1"),
                     port=int(os.environ.get("BIND_PORT", "8080")))
PY

# --- Step 8: launchd plist for encoder ---
log "Step 8: launchd plist for encoder"
PLIST_DIR="${HOME}/Library/LaunchAgents"
mkdir -p "${PLIST_DIR}"
cat > "${PLIST_DIR}/com.aischolar.encoder.plist" <<XML
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyLists-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.aischolar.encoder</string>
  <key>ProgramArguments</key>
  <array>
    <string>${SERVICE_ROOT}/venv/bin/python</string>
    <string>${SERVICE_ROOT}/encoder_service.py</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>BIND_HOST</key><string>${TAILSCALE_IP}</string>
    <key>BIND_PORT</key><string>${ENCODER_PORT}</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${SERVICE_ROOT}/encoder.stdout.log</string>
  <key>StandardErrorPath</key><string>${SERVICE_ROOT}/encoder.stderr.log</string>
  <key>WorkingDirectory</key><string>${SERVICE_ROOT}</string>
</dict>
</plist>
XML

# --- Step 9: launchd plist for LLM (mlx_lm.server, OpenAI-compat shape) ---
log "Step 9: launchd plist for mlx_lm.server (Gemma primary; swap path post-A/B)"
cat > "${PLIST_DIR}/com.aischolar.llm.plist" <<XML
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyLists-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.aischolar.llm</string>
  <key>ProgramArguments</key>
  <array>
    <string>${SERVICE_ROOT}/venv/bin/python</string>
    <string>-m</string><string>mlx_lm.server</string>
    <string>--model</string><string>mlx-community/gemma-3-27b-it-qat-4bit</string>
    <string>--host</string><string>${TAILSCALE_IP}</string>
    <string>--port</string><string>${LLM_PORT}</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${SERVICE_ROOT}/llm.stdout.log</string>
  <key>StandardErrorPath</key><string>${SERVICE_ROOT}/llm.stderr.log</string>
  <key>WorkingDirectory</key><string>${SERVICE_ROOT}</string>
</dict>
</plist>
XML

# --- Step 10: load services ---
log "Step 10: load LaunchAgents"
launchctl unload "${PLIST_DIR}/com.aischolar.encoder.plist" 2>/dev/null || true
launchctl unload "${PLIST_DIR}/com.aischolar.llm.plist" 2>/dev/null || true
launchctl load -w "${PLIST_DIR}/com.aischolar.encoder.plist"
launchctl load -w "${PLIST_DIR}/com.aischolar.llm.plist"

# --- Step 11: smoke ---
log "Step 11: smoke (15s warmup)"
sleep 15
echo "encoder:"
curl -sS "http://${TAILSCALE_IP}:${ENCODER_PORT}/health" || echo "  NOT READY (encoder)"
echo
echo "llm:"
curl -sS "http://${TAILSCALE_IP}:${LLM_PORT}/v1/models" || echo "  NOT READY (llm)"
echo

log "Phase 1 install complete. Tail logs at ${SERVICE_ROOT}/{encoder,llm}.{stdout,stderr}.log"

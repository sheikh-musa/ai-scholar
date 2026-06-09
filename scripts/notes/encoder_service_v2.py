"""bge-m3 encoder + bge-reranker-v2-m3 rerank service.

Endpoints:
  POST /embed   {"inputs": [...]}      -> {"embeddings": [[...]], "dim": 1024}
  POST /rerank  {"query":"...", "passages":[...]} -> {"scores": [...]} (one per passage)
  GET  /health                          -> {"status":"ok", ...}

The reranker loads lazily on first call so /embed stays available even if
the reranker model fails to download. Both models share the MPS device on
the Mac Studio; total resident memory ~10-12 GB combined.
"""
from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer, CrossEncoder
import uvicorn, os, threading

app = FastAPI()
embed_model = SentenceTransformer("BAAI/bge-m3")

# Reranker lazy-load — first call triggers download (~2.3 GB)
_reranker = None
_reranker_lock = threading.Lock()

def _get_reranker():
    global _reranker
    if _reranker is None:
        with _reranker_lock:
            if _reranker is None:
                _reranker = CrossEncoder("BAAI/bge-reranker-v2-m3", max_length=512)
    return _reranker


class EmbedRequest(BaseModel):
    inputs: list[str]

class RerankRequest(BaseModel):
    query: str
    passages: list[str]


@app.post("/embed")
def embed(req: EmbedRequest):
    vecs = embed_model.encode(req.inputs, normalize_embeddings=True).tolist()
    return {"embeddings": vecs, "dim": len(vecs[0]) if vecs else 0}


@app.post("/rerank")
def rerank(req: RerankRequest):
    if not req.passages:
        return {"scores": []}
    reranker = _get_reranker()
    pairs = [(req.query, p) for p in req.passages]
    scores = reranker.predict(pairs).tolist()
    return {"scores": scores}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "embed_model": "BAAI/bge-m3",
        "embed_dim": embed_model.get_sentence_embedding_dimension(),
        "reranker_model": "BAAI/bge-reranker-v2-m3",
        "reranker_loaded": _reranker is not None,
    }


if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("BIND_HOST", "127.0.0.1"),
                     port=int(os.environ.get("BIND_PORT", "8080")))

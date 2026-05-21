#!/usr/bin/env python3
"""Ihsan-grade ingestion pipeline orchestrator.

Operator-in-loop, audit-trail-first corpus ingestion. Recipes (YAML) declare
the desired ingestion; the pipeline fetches sources via adapters, runs
authenticity gates, performs cross-attestation (when ≥2 sources), and writes
a row to ingestion_manifest (status='awaiting_approval'). Operator reviews
the proposed payload, then runs `approve <manifest_id>` to commit.

Subcommands:
  propose <recipe.yaml>          Fetch + gate + attest + manifest-stage.
                                 No writes to target tables.
  list-pending                   Show all manifests awaiting approval.
  show <manifest_id>             Print full manifest detail.
  approve <manifest_id>          Commit proposed rows to target tables.
                                 Requires status=awaiting_approval.
  reject <manifest_id> --reason  Mark manifest rejected. No DB writes.

Recipe shape (YAML):
  target_corpus_label: "Nihāyat al-Zayn"
  manifest_label: "nihayat-zayn-2026-05-22"
  sources:
    - {adapter: openiti, text_uri: "...", edition_uri: "...", section_heading: null}
    - {adapter: openiti, text_uri: "...", edition_uri: "...", section_heading: null}
  attestation:
    require_cross_attest: true       # if false, single-source OK
    primary_source_idx: 0
  juridical_text:                    # shape passed to juridical_texts insert
    text_name: "..."
    baab_or_section: "..."
    baab_order: 10
    author_name: "..."
    author_death_hijri: 1316
    author_death_gregorian: 1898
    madhab: "shafii"
    dalil_strength: "primer_juridical"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from source_adapters import SourceArtifact
from source_adapters.openiti import fetch_openiti
from source_adapters.authenticity import run_gates, summarize, all_hard_passed
from source_adapters.attest import cross_attest, AttestationResult


SUPABASE_URL = os.environ.get("ORCHESTRATOR_SUPABASE_URL", "https://tscuymavysscrvoberrr.supabase.co")
SUPABASE_KEY = os.environ.get("ORCHESTRATOR_SUPABASE_SERVICE_KEY", "") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def _require_key():
    if not SUPABASE_KEY:
        print("ERROR: ORCHESTRATOR_SUPABASE_SERVICE_KEY (or SUPABASE_SERVICE_ROLE_KEY) not set", file=sys.stderr)
        sys.exit(2)


def sha256_hex(text: str) -> str:
    import hashlib
    return hashlib.sha256(unicodedata.normalize("NFC", text).encode("utf-8")).hexdigest()


def supabase_get(table: str, params: dict) -> list:
    _require_key()
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/{table}?{qs}",
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def supabase_post(table: str, data: dict | list) -> list:
    _require_key()
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/{table}",
        data=json.dumps(data).encode("utf-8"),
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def supabase_patch(table: str, row_id: str, data: dict) -> list:
    _require_key()
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/{table}?id=eq.{row_id}",
        data=json.dumps(data).encode("utf-8"),
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        method="PATCH",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_recipe(path: Path) -> dict:
    """Recipe is YAML, but we accept JSON too for zero-dep parsing."""
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    # Minimal YAML parser via PyYAML if available; else strict-JSON-only fallback
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        print(
            "ERROR: PyYAML not installed. Either install (pip install pyyaml) "
            "or convert recipe to .json.",
            file=sys.stderr,
        )
        sys.exit(2)


def fetch_source(spec: dict) -> SourceArtifact:
    """Dispatch to the right adapter based on spec['adapter']."""
    adapter = spec["adapter"]
    if adapter == "openiti":
        return fetch_openiti(
            text_uri=spec["text_uri"],
            edition_uri=spec["edition_uri"],
            section_heading=spec.get("section_heading"),
        )
    raise ValueError(f"unknown adapter: {adapter}")


# ---------------------------------------------------------------------------
# propose
# ---------------------------------------------------------------------------

def cmd_propose(args):
    """Run a recipe through the pipeline; stage to ingestion_manifest."""
    _require_key()
    recipe_path = Path(args.recipe)
    if not recipe_path.exists():
        print(f"ERROR: recipe not found: {recipe_path}", file=sys.stderr)
        return 2
    recipe = load_recipe(recipe_path)
    label = recipe["manifest_label"]

    # Idempotency check
    existing = supabase_get("ingestion_manifest", {
        "manifest_label": f"eq.{urllib.parse.quote(label)}",
        "status": "in.(awaiting_approval,approved,committed)",
        "select": "id,status",
        "limit": "1",
    })
    if existing:
        print(f"  manifest '{label}' already exists: id={existing[0]['id']}, "
              f"status={existing[0]['status']}")
        return 0

    # 1. Fetch all sources
    print(f"Fetching {len(recipe['sources'])} source(s)...")
    artifacts: list[SourceArtifact] = []
    for i, src_spec in enumerate(recipe["sources"]):
        print(f"  [{i+1}/{len(recipe['sources'])}] {src_spec.get('adapter')}: "
              f"{src_spec.get('text_uri', src_spec.get('source_url', '?'))}")
        try:
            art = fetch_source(src_spec)
        except Exception as e:
            print(f"  ✗ fetch failed: {type(e).__name__}: {e}", file=sys.stderr)
            return 3
        artifacts.append(art)
        print(f"     {art.byte_length} bytes, sha={art.sha256[:16]}")

    # 2. Authenticity gates
    print(f"\nRunning authenticity gates per source...")
    all_results: list = []
    for i, art in enumerate(artifacts):
        gate_results = run_gates(art)
        all_results.append([
            {"name": r.name, "passed": r.passed, "severity": r.severity,
             "value": str(r.value)[:200], "threshold": str(r.threshold)[:80], "message": r.message}
            for r in gate_results
        ])
        print(f"  source #{i+1}:")
        print(summarize(gate_results).replace("\n", "\n  "))
        if not all_hard_passed(gate_results):
            print(f"  ✗ source #{i+1} FAILED hard gates; pipeline aborts", file=sys.stderr)
            return 4

    # 3. Cross-attestation (if multi-source)
    attestation_json = None
    cross_attested_pairs: list = []
    primary_idx = recipe.get("attestation", {}).get("primary_source_idx", 0)
    require_cross = recipe.get("attestation", {}).get("require_cross_attest", True)
    if len(artifacts) >= 2:
        print(f"\nCross-attestation: source #{primary_idx+1} as primary")
        primary = artifacts[primary_idx]
        for i, art in enumerate(artifacts):
            if i == primary_idx:
                continue
            result = cross_attest(primary, art)
            cross_attested_pairs.append(result.to_jsonable())
            print(f"  primary vs source #{i+1}: "
                  f"tokenJ={result.token_jaccard:.4f} trigramJ={result.trigram_jaccard:.4f} "
                  f"lengthR={result.length_ratio:.4f} → {'PASS' if result.passed else 'REJECT'}")
            if require_cross and not result.passed:
                print(f"  ✗ cross-attestation REJECTED; pipeline aborts", file=sys.stderr)
                return 5
        attestation_json = {"pairs": cross_attested_pairs}
    elif require_cross:
        print(f"  ✗ recipe requires cross-attestation but only 1 source provided", file=sys.stderr)
        return 5

    # 4. Compose proposed rows
    primary = artifacts[primary_idx]
    proposed_provenance_rows = [
        {
            **art.provenance_fields,
            "source_file_sha256": art.sha256,
        }
        for art in artifacts
    ]
    jt_spec = recipe.get("juridical_text", {})
    proposed_content_rows = [
        {
            "table": "juridical_texts",
            "text_name": jt_spec["text_name"],
            "author_name": jt_spec["author_name"],
            "author_death_hijri": jt_spec.get("author_death_hijri"),
            "author_death_gregorian": jt_spec.get("author_death_gregorian"),
            "madhab": jt_spec.get("madhab", "shafii"),
            "dalil_strength": jt_spec.get("dalil_strength", "primer_juridical"),
            "baab_or_section": jt_spec["baab_or_section"],
            "baab_order": jt_spec.get("baab_order"),
            "arabic_text": primary.content,
            "arabic_text_sha256": primary.sha256,
            # ingestion_provenance_id filled at approve-time (after provenance row created)
        }
    ]

    # 5. Stage to ingestion_manifest
    manifest_row = {
        "manifest_label": label,
        "target_tables": ["ingestion_provenance", "juridical_texts"],
        "target_corpus_label": recipe.get("target_corpus_label"),
        "source_artifacts": [
            {
                "adapter": art.adapter_name,
                "source_url": art.source_url,
                "sha256": art.sha256,
                "bytes": art.byte_length,
                "metadata": {k: str(v)[:200] for k, v in art.metadata.items()},
                "content_preview": art.content_preview(300),
            }
            for art in artifacts
        ],
        "authenticity_gates": {
            "per_source": all_results,
            "all_hard_passed": True,
        },
        "attestation": attestation_json,
        "proposed_provenance_rows": proposed_provenance_rows,
        "proposed_content_rows": proposed_content_rows,
        "status": "awaiting_approval",
        "notes": f"Pipeline propose run from recipe {recipe_path.name} at "
                 f"{datetime.now(timezone.utc).isoformat()}",
    }
    result = supabase_post("ingestion_manifest", manifest_row)
    mid = result[0]["id"]
    print(f"\n✓ Manifest staged: id={mid} (status=awaiting_approval)")
    print(f"  Review with:  python3 scripts/ingest_pipeline.py show {mid}")
    print(f"  Approve with: python3 scripts/ingest_pipeline.py approve {mid}")
    return 0


# ---------------------------------------------------------------------------
# list-pending
# ---------------------------------------------------------------------------

def cmd_list_pending(_args):
    rows = supabase_get("ingestion_manifest", {
        "status": "eq.awaiting_approval",
        "select": "id,manifest_label,target_corpus_label,created_at",
        "order": "created_at.desc",
    })
    print(f"Manifests awaiting approval: {len(rows)}")
    for r in rows:
        print(f"  {r['id']}  {r['created_at'][:19]}  {r['manifest_label']}  "
              f"({r.get('target_corpus_label', '?')})")
    return 0


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------

def cmd_show(args):
    rows = supabase_get("ingestion_manifest", {
        "id": f"eq.{args.manifest_id}",
        "select": "*",
        "limit": "1",
    })
    if not rows:
        print(f"ERROR: manifest {args.manifest_id} not found", file=sys.stderr)
        return 4
    m = rows[0]
    print(f"=== Manifest {m['id']} ===")
    print(f"  label:    {m['manifest_label']}")
    print(f"  corpus:   {m.get('target_corpus_label', '?')}")
    print(f"  status:   {m['status']}")
    print(f"  created:  {m['created_at']}")
    print(f"\n  Sources ({len(m['source_artifacts'])}):")
    for src in m["source_artifacts"]:
        print(f"    - {src['adapter']}: {src['source_url']}")
        print(f"      {src['bytes']} bytes, sha={src['sha256'][:16]}")

    if m.get("attestation"):
        print(f"\n  Cross-attestation:")
        for pair in m["attestation"]["pairs"]:
            print(f"    tokenJ={pair['token_jaccard']} trigramJ={pair['trigram_jaccard']} "
                  f"lengthR={pair['length_ratio']} → {'PASS' if pair['passed'] else 'REJECT'}")
            if pair.get("sample_diffs"):
                d = pair["sample_diffs"]
                if d.get("only_in_first") or d.get("only_in_second"):
                    print(f"    sample diffs:")
                    print(f"      only in first: {d.get('only_in_first', [])[:8]}")
                    print(f"      only in second: {d.get('only_in_second', [])[:8]}")

    print(f"\n  Proposed provenance rows ({len(m['proposed_provenance_rows'])}):")
    for pr in m["proposed_provenance_rows"]:
        print(f"    - source_url: {pr['source_url']}")
        print(f"      maintainer: {pr['source_maintainer']}")
        print(f"      license:    {pr['license_declaration'][:100]}...")
        print(f"      sha256:     {pr['source_file_sha256'][:32]}...")

    print(f"\n  Proposed content rows ({len(m['proposed_content_rows'])}):")
    for cr in m["proposed_content_rows"]:
        print(f"    - {cr['table']}: text={cr.get('text_name')} "
              f"baab={cr.get('baab_or_section')} {len(cr.get('arabic_text', ''))}c")

    if m.get("approved_by"):
        print(f"\n  approved by:  {m['approved_by']} via {m.get('approved_via', '?')} "
              f"at {m.get('approved_at', '?')}")
    if m.get("committed_provenance_ids"):
        print(f"  committed provenance: {m['committed_provenance_ids']}")
    if m.get("committed_content_ids"):
        print(f"  committed content:    {m['committed_content_ids']}")
    return 0


# ---------------------------------------------------------------------------
# approve
# ---------------------------------------------------------------------------

def cmd_approve(args):
    """Commit a staged manifest. Writes proposed_provenance_rows + proposed_content_rows
    to target tables, cross-linking ingestion_provenance_id and cross_attested_with."""
    rows = supabase_get("ingestion_manifest", {
        "id": f"eq.{args.manifest_id}",
        "select": "*",
        "limit": "1",
    })
    if not rows:
        print(f"ERROR: manifest {args.manifest_id} not found", file=sys.stderr)
        return 4
    m = rows[0]
    if m["status"] != "awaiting_approval":
        print(f"ERROR: manifest status is '{m['status']}', expected 'awaiting_approval'",
              file=sys.stderr)
        return 4

    approver = args.approver or os.environ.get("USER", "unknown")

    # 1. Insert provenance rows (idempotent on SHA — retry-safe)
    print(f"Committing {len(m['proposed_provenance_rows'])} provenance row(s)...")
    committed_provenance_ids: list = []
    for pr in m["proposed_provenance_rows"]:
        sha = pr["source_file_sha256"]
        existing = supabase_get("ingestion_provenance", {
            "source_file_sha256": f"eq.{sha}",
            "select": "id", "limit": "1",
        })
        if existing:
            committed_provenance_ids.append(existing[0]["id"])
            print(f"  = provenance: id={existing[0]['id']} sha={sha[:16]} (already present, reused)")
            continue
        pr_clean = {k: v for k, v in pr.items() if v is not None}
        pr_clean["ihsan_pipeline_manifest_id"] = m["id"]
        result = supabase_post("ingestion_provenance", pr_clean)
        committed_provenance_ids.append(result[0]["id"])
        print(f"  + provenance: id={result[0]['id']} sha={sha[:16]}")

    # 2. Cross-link provenance rows (set cross_attested_with arrays)
    if len(committed_provenance_ids) >= 2 and m.get("attestation"):
        print(f"  Cross-linking {len(committed_provenance_ids)} provenance rows...")
        attestation = m["attestation"]
        avg_levenshtein = sum(
            p["token_jaccard"] for p in attestation["pairs"]
        ) / max(1, len(attestation["pairs"]))
        for pid in committed_provenance_ids:
            others = [pid2 for pid2 in committed_provenance_ids if pid2 != pid]
            supabase_patch("ingestion_provenance", pid, {
                "cross_attested_with": others,
                "levenshtein_to_attestor": round(avg_levenshtein, 4),
            })

    # 3. Insert content rows
    print(f"Committing {len(m['proposed_content_rows'])} content row(s)...")
    primary_provenance_id = committed_provenance_ids[0]
    committed_content_ids: list = []
    for cr in m["proposed_content_rows"]:
        cr_clean = {k: v for k, v in cr.items() if v is not None and k != "table"}
        cr_clean["ingestion_provenance_id"] = primary_provenance_id
        target_table = cr["table"]
        result = supabase_post(target_table, cr_clean)
        committed_content_ids.append(result[0]["id"])
        print(f"  + {target_table}: id={result[0]['id']}")

    # 4. Update manifest to status='committed'
    supabase_patch("ingestion_manifest", m["id"], {
        "status": "committed",
        "approved_by": approver,
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "approved_via": "cli",
        "committed_provenance_ids": committed_provenance_ids,
        "committed_content_ids": committed_content_ids,
        "committed_at": datetime.now(timezone.utc).isoformat(),
    })
    print(f"\n✓ Manifest committed: provenance={committed_provenance_ids} "
          f"content={committed_content_ids}")
    return 0


# ---------------------------------------------------------------------------
# reject
# ---------------------------------------------------------------------------

def cmd_reject(args):
    rows = supabase_get("ingestion_manifest", {
        "id": f"eq.{args.manifest_id}",
        "select": "id,status",
        "limit": "1",
    })
    if not rows:
        print(f"ERROR: manifest {args.manifest_id} not found", file=sys.stderr)
        return 4
    if rows[0]["status"] != "awaiting_approval":
        print(f"ERROR: cannot reject; status is '{rows[0]['status']}'", file=sys.stderr)
        return 4
    supabase_patch("ingestion_manifest", args.manifest_id, {
        "status": "rejected",
        "notes": f"Rejected: {args.reason}",
        "approved_by": args.approver or os.environ.get("USER", "unknown"),
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "approved_via": "cli",
    })
    print(f"✓ Manifest {args.manifest_id} rejected: {args.reason}")
    return 0


SUBCOMMANDS = {
    "propose": cmd_propose,
    "list-pending": cmd_list_pending,
    "show": cmd_show,
    "approve": cmd_approve,
    "reject": cmd_reject,
}


def main():
    parser = argparse.ArgumentParser(description="Ihsan ingestion pipeline orchestrator")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_prop = sub.add_parser("propose"); p_prop.add_argument("recipe")
    sub.add_parser("list-pending")
    p_show = sub.add_parser("show"); p_show.add_argument("manifest_id")
    p_app = sub.add_parser("approve"); p_app.add_argument("manifest_id"); p_app.add_argument("--approver")
    p_rej = sub.add_parser("reject"); p_rej.add_argument("manifest_id")
    p_rej.add_argument("--reason", required=True); p_rej.add_argument("--approver")
    args = parser.parse_args()
    return SUBCOMMANDS[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main() or 0)

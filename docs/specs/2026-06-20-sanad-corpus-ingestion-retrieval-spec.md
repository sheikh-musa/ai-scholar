# Authoritative Sanad-Corpus: Ingestion + Retrieval Design Spec

- **Status:** DESIGN ONLY — no ingestion, no scraping, no schema applied. Build is gated (see §7).
- **Authored:** cc-scholar, 2026-06-20
- **Requested by:** cc-orchestrator agent_messages #2747; safety framework from #2752 / CAI-RESP-287
- **Default posture:** **partner + attribute, NEVER scrape.** MUIS is a government body; ARS-certified asātiżah repositories are the scholars' own work.
- **Build gates:** (i) ≥1 documented per-source written consent **and** (ii) operator + cai strategic/legal clearance. Until both clear, this stays a paper design.

---

## 1. Purpose

Today every Al-Mīzān answer is AI-generated (Class B). The operator's vision: when a user asks something a qualified human scholar has **already answered authoritatively**, surface that verified answer **with its sanad (chain of authority)** instead of generating a fresh AI draft. This raises the ceiling from "AI draft pending review" to "attributed scholar's ruling" for the subset of questions the corpus covers — and leaves everything else on the existing generate-then-flag path.

This is the substrate for **Class A** of the CAI-RESP-287 three-class framework.

---

## 2. The three-class answer framework (CAI-RESP-287) — the spine of this spec

| Class | What it is | Source | Tier | UI treatment |
|---|---|---|---|---|
| **A — Attributed** | A **verbatim/exact excerpt** of a consented human-scholar answer, full provenance | Sanad-corpus, exact source-linked match above HIGH confidence | `quoted` | Distinct "Attributed scholar's answer" frame + full sanad block |
| **B — AI draft** | AI synthesis over retrieved tafsīr/ḥadīth/fiqh | Claude over corpus | `inferred` / `ai-generated` | "AI draft — not a fatwa" disclaimer (LIVE as of #2752) |
| **C — Routed** | High-stakes/irreversible → no AI ruling, route to human | n/a (refusal) | `ai-generated` | "Consult a qualified scholar" + flag-to-queue (LIVE as of #2752) |

**HARD SEPARATION (non-negotiable).** Class A and Class B must be **visually and structurally distinct** so a user always knows whether they are reading an attributed scholar's ruling or an AI draft. Rules:

- **No mixing.** If *any* AI-generated connective text is woven into a Class A answer, the whole response is **Class B**, not A. Paraphrasing a fatwā alters the ruling — Class A is **verbatim only**, never summarized, never "lightly edited."
- A Class A response renders the scholar answer in a quoted block with a sanad header and **no** AI commentary in the same message. If the bot wants to add framing, it is a *separate* Class-B-labelled message.
- Class A carries **no** "AI draft" disclaimer (it isn't one); it carries the **sanad/attribution** block instead.

This maps cleanly onto the existing 4-tier-transparency invariant: Class A = `quoted` with a named source; tier collapse (shipping AI text as `quoted`) is already a system error.

---

## 3. Source enumeration + classification

> ⚠️ **Legal posture below is a first-pass assessment by cc-scholar, NOT verified legal advice.** Every "usable" verdict requires (a) reading the source's actual licence/ToS verbatim — per the standing rule not to project secular all-rights-reserved defaults onto Islamic religious publishing — and (b) cai+operator sign-off before any fetch. Default to *partner + written consent* even where content looks open.

| # | Source | Nature | Madhhab fit | First-pass posture | Build verdict |
|---|---|---|---|---|---|
| 1 | **MUIS Fatwa archive** (Office of the Mufti, muis.gov.sg) | Singapore statutory board; official fatāwā | Shāfiʿī-majority (local) ✓ | Government work — likely Crown/Govt copyright + site ToS. **Partner, do not scrape.** Approach via MUIS directly for an attribution agreement / API. | **PERMISSION REQUIRED** — design only |
| 2 | **ARS-certified asātiżah repositories** (individual certified teachers' Q&A/writings) | Private scholars' own IP, ARS-credentialled | Mostly Shāfiʿī ✓ | Each is the scholar's own work → per-scholar written consent (attribution format, scope, takedown). | **PERMISSION REQUIRED (per scholar)** — design only |
| 3 | **MuslimSG / Muslim.sg** (MUIS community platform) | MUIS-run articles/Q&A | Local ✓ | MUIS property; same partnership track as #1. | **PERMISSION REQUIRED** — design only |
| 4 | **PERGAS** (Singapore Islamic Scholars & Religious Teachers Assoc.) | Scholarly body publications/position papers | Local ✓ | Org IP → partnership/consent. | **PERMISSION REQUIRED** — design only |
| 5 | **Existing in-corpus licensed texts** (Safīnat al-Najā / Kashifat al-Sajā al-Marbūqī tr., already ingested) | Classical matn, already in DB | Shāfiʿī ✓ | Already cleared + ingested under existing posture. | **USABLE** (already in pipeline) — but it's *matn*, not Q&A-with-sanad |
| 6 | International Q&A sites (SeekersGuidance, Daruliftaa, Shafiifiqh.com, IslamQA) | Foreign fatāwā/Q&A | Mixed (some Ḥanafī; IslamQA Salafī — madhhab mismatch) | Restrictive ToS typical; madhhab/manhaj divergence risk; **not aligned with the local Shāfiʿī authority the operator wants.** | **OUT OF SCOPE for v1** (note only) |

**Key takeaway:** the two sources that realize the operator's vision (MUIS #1, ARS asātiżah #2) are **both permission-required**. Therefore **no ingestion code is written for either until consent is documented.** The only "openly usable" lane today (#5) is already in the corpus and is classical matn, not sanad-bearing Q&A — so it does not unblock Class A on its own.

---

## 4. Sanad-preserving schema (proposed — NOT applied)

Sanad is **mandatory metadata, not optional**. Proposed table `authoritative_answers`:

| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `source_id` | text NOT NULL | FK → `authoritative_sources` (the consented source registry) |
| `answering_scholar` | text NOT NULL | named individual or body (e.g. "MUIS Fatwa Committee") |
| `scholar_credential` | text NOT NULL | ARS cert no. / MUIS office / ijāza — the *sanad* |
| `issuing_body` | text | MUIS, PERGAS, etc. |
| `madhhab` | text | Shāfiʿī / Ḥanafī / … |
| `question_text` | text NOT NULL | original question, verbatim |
| `answer_text` | text NOT NULL | **verbatim** answer — never paraphrased |
| `source_url` | text NOT NULL | canonical link |
| `source_date` | date | when issued/published |
| `consent_ref` | text NOT NULL | FK → the written-consent record authorizing relay/index |
| `output_tier` | text NOT NULL CHECK in ('quoted',…) | **always `quoted`** for this table (T-1) |
| `lang` | text | en / ms / ar |
| `embedding` | vector | for semantic match (§5) |
| `content_hash` | text | NFC+SHA-256 of answer_text — integrity + dedupe (§6) |
| `ingested_at` | timestamptz | |

Companion `authoritative_sources` registry: `source_id, name, nature (govt/org/individual), consent_status, consent_doc_url, attribution_format, scope, takedown_path, disclaimer_text`. **A row is ingestible only when `consent_status='granted'` with a `consent_doc_url`.** This is the schema-level enforcement of "build gated on consent."

Note `scholar_credential` + `consent_ref` are NOT NULL by design: an answer with no sanad and no consent **cannot be stored**, so Class A can never be served from un-sourced data.

---

## 5. Retrieval: match-or-generate

Wire the sanad-corpus as a **pre-stage** to the existing pipeline, preserving the F-1 tafsīr-defense funnel (retrieval before synthesis — unchanged):

```
user query
   │
   ├─► authoritative-corpus semantic match (bge-m3 embeddings + rerank, same stack as fiqh_semantic)
   │        │
   │        ├─ top-1 score ≥ HIGH_THRESHOLD  ──► CLASS A: surface verbatim + sanad. STOP. (no LLM)
   │        │
   │        └─ below threshold ──────────────────┐
   │                                             ▼
   └─────────────────────────────► existing generate-then-flag path (Class B) ── unchanged
```

- **Matching:** semantic embeddings (reuse the deployed `bge-m3` + `bge-reranker-v2-m3` stack and the `match_*_embeddings` RPC pattern already in the repo) over `question_text`. Lexical FTS as a secondary signal.
- **HIGH_THRESHOLD (conservative).** Class A only fires on a genuinely close, source-linked match. Start strict (proposed rerank score ≥ **0.80**, to be calibrated against a labelled match/no-match set before launch — same calibration discipline as the mizan_judge gate). **Never present a loose match as authoritative.** When in doubt → fall through to Class B. A false Class A (attributing the wrong ruling to a named scholar) is the worst failure mode in the whole system.
- **No semantic drift across madhhab:** prefer a same-madhhab match; a cross-madhhab hit must not be surfaced as Class A for a user with a stated school.
- **UI distinction (hard separation, §2):** Class A renders as

  > 📜 **Attributed answer — [Scholar], [credential]**
  > [verbatim answer]
  > *Source: [body], [date] · [link]*
  > *Relayed/indexed by Al-Mīzān; the scholar is the issuer.*

  Visually unlike a Class B answer (no 💭/AI-draft footer; a distinct 📜 sanad frame). The two are never in the same message.

---

## 6. Ingestion flow (for consented sources ONLY)

Per source, only after `consent_status='granted'`:

1. **Fetch** via the agreed channel (API/feed/supplied export — *not* a scraper for a permission-required source).
2. **Normalize** to the §4 shape; NFC-normalize text (Quranic-text-integrity discipline), capture `scholar_credential` + `source_url` + `consent_ref` (reject the record if any is missing).
3. **Dedupe** on `content_hash` (NFC+SHA-256 of `answer_text`).
4. **Embed** (`bge-m3`) and store.
5. **Audit:** every ingested row references its `consent_ref`; takedown = delete-by-source honoring the agreed takedown path.

---

## 7. Build gates + open questions (for cai + operator)

**Gates (all must clear before any code):**
1. ≥1 documented per-source **written consent** (attribution format, scope, takedown/revision path, and an explicit disclaimer that we *relay/index* while the scholars remain the *issuers*).
2. Operator + cai strategic read on the MUIS / ARS partnership + legal posture (in flight per #2747).

**Open questions:**
- Does MUIS offer a fatwā API / data-sharing agreement, or is the path a formal partnership? (determines #1 feasibility)
- ARS consent: per-scholar, or is there an umbrella body (PERGAS/MUIS) that can authorize a set?
- Attribution wording MUIS/ARS will require — must be fixed *before* UI design freezes the Class A frame.
- Calibration set owner for HIGH_THRESHOLD (proposed: same human-review loop as mizan_eval_set).
- Liability/disclaimer language for relaying a govt fatwā (PDPA-processor posture; we are an indexer, not the issuer).

**What is NOT in this spec / NOT being built:** any scraper, any schema apply, any fetch of a permission-required source. This document is the paper trail that lets that work start *cleanly* once consent + clearance land.

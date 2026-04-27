# LAYERING — disambiguating the two "L_n" systems in Al-Bayān

**Status:** Source of truth. Authored 2026-04-28 per ARCH-AL-BAYAN-LAYERING-RECONCILE (id 569).
**Required reading** before any further L-prefix `strategic_decisions` row, code comment, or filing.

## Why this glossary exists

Two layering systems coexist in Al-Bayān and they collided on the word "L3":

- **content_layer** describes WHAT a piece of content IS in Islamic epistemology — Quran vs tafsir vs fiqh vs connective material. Stable, theological, unchanging.
- **system_layer** describes WHICH ENGINEERING RESPONSIBILITY a piece of code owns — corpus storage vs retrieval vs knowledge graph vs scholar pairing. Engineering scaffold; codified in CAI-RESP-094.

Same word "L3" — different referents. AL-BAYAN-003 (juridical content) and CAI-RESP-094 system_layer L3 (knowledge graph) are NOT the same thing. Disambiguating now is cheap; disambiguating in 3 months when 30 filings depend on bare "L_n" is expensive.

---

## content_layer (Islamic ontology — what the content IS)

Four values, in increasing distance from the primary text:

| Value | What it contains | Examples in our corpus |
|---|---|---|
| **primary** | Revelation itself — Quran (KFGQPC Hafs); sahih hadith with isnad | `ayat` table; `hadith_entries` |
| **interpretive** | Scholarly explanation of the primary text | `tafsir_entries` (Ibn Kathir, Al-Sa'di); `asbab_nuzul` |
| **juridical** | Derivation of rulings from primary + interpretive layers, organized by madhab | `juridical_texts` (planned per AL-BAYAN-003): Safīnat al-Najā, Matn Abī Shujā', Fath al-Mu'īn |
| **connective** | Cross-references and structural relationships between content items | `mutashabihat`, ayah ↔ hadith bridges, isnad chains, asl→far' qiyas links |

**Citation rule (extends across all four):** every retrieved item surfaces with explicit source identification — name, location, layer, dalil_strength_tier — never collapsed into "Islam says X" authority-performance (per AL-BAYAN-002, AL-BAYAN-003 citation-rendering rule).

---

## system_layer (engineering scaffold — what the code DOES)

Eight numbered values, in build order from substrate to product:

| Layer | Responsibility | Status (2026-04-28) |
|---|---|---|
| **L1** | Corpus storage — text, hash-verified provenance, ingestion audit trail | Quran ✓ (KFGQPC, hashed); hadith partial; juridical Phase 1 in flight per AL-BAYAN-003 |
| **L2** | Retrieval substrate — semantic + lexical fusion (RRF), reranker | EMBED_PIPELINE_v02 in flight per CAI-RESP-094/095 |
| **L3** | Knowledge graph — explicit edges between content items (mutashabihat extension to isnad / teacher chains / qiyas) | Partial (mutashabihat live); v0.3+ scope |
| **L4** | Madhab parameterization — request-shape and retrieval honor declared madhab | Schema-supported per AL-BAYAN-003; activation gates on L7 |
| **L5** | Lineage transparency — every cited ruling shows chain back to a named source | 4-tier-transparency primitive live; full lineage gates on L7 |
| **L6** | Refusal-as-feature — aggressive "I don't know, ask a living scholar" on novel questions | Scholar-gate primitive in ask-scholar; expands with L7 |
| **L7** | Scholar-of-record pairing — paired human scholar reviews + signs ruling-class output | INV-7 obligation; Musa direct action; first pairing pending |
| **L8** | Red-team adversarial loop — system grades own resistance to softening / sectarian inject / fitnah framing | mizan_judge pipeline partial; continuous-mode v0.3+ |

**Codified in:** CAI-RESP-094 (decision id 562). Authored by cc-scholar.

---

## Cross-mapping

| content_layer | served by which system_layer? |
|---|---|
| primary | L1 (storage) → L2 (retrieval) → L3 (mutashabihat-style cross-refs) |
| interpretive | L1 → L2 → L3 (asbab→ayah edges) |
| juridical | L1 → L2 → L3 (madhab consensus / contested mapping); L4 honors madhab at retrieval-time |
| connective | L3 IS the engineering home for connective content (graph edges); produced from L1 sources |

**Important:** system_layer L3 (knowledge graph) consumes content from ALL FOUR content_layers. It is NOT itself a content_layer. The opposite confusion (treating juridical as system_layer L3) is the exact collision this glossary prevents.

---

## Correct usage examples

| ✓ Correct | ✗ Wrong |
|---|---|
| "AL-BAYAN-003 ingests **content_layer juridical** corpus" | "AL-BAYAN-003 ingests **L3** corpus" |
| "EMBED_PIPELINE_v02 implements **system_layer L2**" | "EMBED_PIPELINE_v02 implements **L2**" (ambiguous: L2 of what?) |
| "**system_layer L3** knowledge graph reads from **content_layer interpretive**" | "L3 reads from L2" |
| "**system_layer L7** scholar-pairing gates **content_layer juridical** activation" | "L7 gates L3" |
| "the **content_layer juridical** value `juridical_texts.dalil_strength` is `primer_juridical`" | "the L3 dalil_strength is primer_juridical" |

Bare "L_n" usage is **forbidden** in any future strategic_decisions row, code comment, repo doc, or agent_messages body. Always qualify with `system_layer` or `content_layer` prefix. Single-source-of-truth for terminology is this file.

---

## Backfill obligation

Per ARCH-AL-BAYAN-LAYERING-RECONCILE constraint, the following must be updated within 7 days (by 2026-05-05) to use disambiguated terminology where currently ambiguous:

- CAI-RESP-094 (decision text) — CAI authors
- CAI-RESP-095 (decision text) — CAI authors
- AL-BAYAN-002 (decision text) — cc-scholar (already updating per CAI-RESP-095 (C))
- AL-BAYAN-003 (decision text) — CAI authors
- `docs/EMBED_PIPELINE_v02.md` — cc-scholar
- `docs/ARCH_AL_BAYAN_ENCODER_EVAL.md` — cc-scholar
- `supabase/migrations/20260428_005_mizan_judge_shadow.sql` (comment block) — cc-scholar

No supersession needed — terminology refinement only.

---

## Out of scope for this glossary

- Changing the value names within either layering system (primary/interpretive/juridical/connective stays; L1-L8 stays)
- Adding a third layering system — any future "layer" must integrate into one of these two existing systems OR be filed as its own architectural decision

---

## References

- ARCH-AL-BAYAN-LAYERING-RECONCILE (decision id 569) — the ruling that mandated this file
- CAI-RESP-094 (id 562) — established system_layer L1-L8 scaffold
- AL-BAYAN-001 — established content_layer ontology
- AL-BAYAN-003 (id 568) — first cross-system filing that benefits from disambiguation

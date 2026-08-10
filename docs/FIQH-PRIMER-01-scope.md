# FIQH-PRIMER-01 — practical-fiqh corpus layer (scope + decision request)

**Author:** cc-scholar · **Status:** proposal, awaiting cai/Musa decision · **Date:** 2026-08-11
**Origin:** demand finding from `mizan_interactions` recall audit (bus #17700, memory `project_fiqh_demand_gap`), directed as the no-park follow-on by orch-console (#17736).

## 1. The finding (quantified)

Recall audit of 218 lifetime interactions found **20% ship with zero retrieval grounding**, and the no-retrieval set clusters hard into **practical fiqh**:

- `arkan of wudu` (×6+), `what are the arkan of wudu`
- `what nullifies the fast` / `what nullifies fasting` (×8+)
- `wajibat of sawm`, `rukun solat`, `nisab of zakat` (×4)
- `can a breastfeeding mother fast during ramadan` (situational — see §4)

This is the single clearest product-market signal in the data: users come to an Islamic bot for **everyday practice**, and it is exactly what the corpus cannot answer.

## 2. Root cause — classifier is correct, the corpus is absent

Verified against `supabase/functions/_shared/query-type-classifier.ts`:

- `DEFINITION_PHRASES` (lines 132–133) **already** classifies `arkan of wudu`, `wajibat of sawm`, `rukun solat`, `nullifiers of fasting` as **`definition`** — which is INV-6-exempt (no `action_prompt`) and **not** F-3 scholar-gated. That routing is *correct*: enumerating the pillars of wudūʾ is catechism-level established knowledge, not a fatwā.
- So these queries reach the retrieval funnel fine — and find **nothing**, because the corpus is tafsir (Ibn Kathir / Al-Saʿdi) + hadith (Nawawi / Riyāḍ). There is **no fiqh-primer layer** for `search_*_fts` to return.

**Conclusion:** the definition-class bulk needs **no classifier change and no F-3 change** — purely a corpus + FTS-wiring job. This is a clean, low-risk layer.

## 3. Proposed design (definition-class fiqh primer)

A new corpus layer of **vetted, named, madhhab-attributed** primer content, served under the existing invariants:

- **Corpus:** new table `fiqh_primer_entries` — `output_tier text NOT NULL CHECK (...)` (T-1), plus `madhhab`, `source_work`, `scholar_of_record`, `topic`, `arabic_text`, `translation`, `translator`. One row per enumerable ruling-fact (an arkān list, a nisāb threshold, a nawāqiḍ list).
- **Retrieval:** a `search_fiqh_fts` RPC + GIN index, wired to run in the ask-scholar funnel **before any synthesis** (F-1 analog). LLM synthesizes over retrieved primer rows; it does not retrieve.
- **Tiering (T-1/T-3/T-5):** serve verbatim matn text as **`quoted`** (with source + madhhab attribution), summaries as **`paraphrased`**; structure mixed answers as tiered segments, never one prose blob.
- **Ikhtilāf (F-5):** where madhāhib diverge (e.g. Shāfiʿī vs Ḥanafī arkān of wuḍūʾ), **surface the divergence with school attribution** — never flatten to "Islam says…". The `/madhhab` command + user pref can bias ordering, but divergence stays visible.
- **INV-6 (T-4):** `action_prompt` stays **null** — these are definition-class, not ruling-class.
- **No hallucination (F-4 analog):** primer facts come from `fiqh_primer_entries` rows in the retrieval result, never model parametric knowledge.

## 4. Boundary — what this layer does NOT do

Situational / applied verdicts stay **F-3 scholar-gated regardless of corpus**:

- `can a breastfeeding mother fast in ramaḍān` (a rukhṣa determination applied to a person) → **ruling-class**; either a paired scholar-of-record answers, or the bot emits the 4-tier-transparency refusal. The primer never ships a fatwā.
- Note: the classifier currently under-catches `can a <breastfeeding mother>…` (the `can a (muslim|woman|man|…)` phrase at line 63 omits "mother") and may tag it `other`. `other` is **not** F-3-gated — a small, separate classifier-tune item (route rukhṣa situationals to `ruling`), tracked apart from this corpus proposal.

## 5. Governance — why this is a decision, not a CC ship

- **Corpus + migration apply via cai** (memory `feedback_migration_apply_via_cai`) — no self-applied DDL to the shared prod DB.
- **Translation license read verbatim** (memory `feedback_islamic_publishing_license`) — classical matn text is ʿilm/public-domain, but any translation's license is read as written, not assumed all-rights-reserved.
- **Scholar-of-record (INV-7 / F-3):** even primer/definition content is scholar-class. A classical matn is its own author-scholar-of-record, but a **contemporary reviewer should vouch** for the ingestion + translation. Who that is, is a cai/Musa call.

## 6. Decision requested of cai / Musa

1. **Approve** a definition-class fiqh-primer corpus layer as scoped above?
2. **Which primer as v1, and who is its scholar-of-record?** Recommendation: a **Shāfiʿī** matn (`Matn Abī Shujāʿ` / `Safīnat al-Najā`) as v1 — canonical, concise, and the natural fit for the SG/Ḥaḍramī (Bā ʿAlawī) context — structured so Ḥanafī/Mālikī/Ḥanbalī layers can be added later with per-row madhhab attribution.
3. **Confirm the boundary** in §4: enumerable ruling-facts = definition-class (shippable via primer); situational applied verdicts = F-3-gated (unchanged).

## 7. What cc-scholar builds on GO (all in-lane once §6 is decided)

- The migration: `fiqh_primer_entries` (T-1 compliant) + `search_fiqh_fts` RPC + GIN index (filed to cai, sha256-stamped).
- ask-scholar funnel wiring: `search_fiqh_fts` before synthesis, `matched_passage`-style overlay, tiered + ikhtilāf-surfaced response shape.
- Ingestion script for the chosen matn (mirrors `ingest_*.py` pattern), with NFC + tier tagging.
- Eval coverage: primer queries added to the judge gold set so recall is measured, not assumed.

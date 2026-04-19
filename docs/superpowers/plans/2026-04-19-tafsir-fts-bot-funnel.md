# Phase 1 — Tafsir FTS in Bot Funnel (Option C)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the ai-scholar search funnel so Telegram users receive scholar-attributed tafsir passages when their query matches tafsir commentary (not just Quran translation). Every surfaced passage must carry an AL-BAYAN-001 four-tier attribution marker.

**Architecture:** A new Postgres RPC `search_tafsir_fts(query, lim)` runs GIN-backed full-text search on `tafsir_entries.english_text`, returning ayah-joined matches with `ts_rank`. The `ask-scholar` Edge Function wires this as a new pipeline stage after ayat-FTS. Both Telegram adapters (`albayan_bot.py`, `mizan_bot.py`) render matched tafsir passages alongside the linked ayah, each wrapped in a tier marker derived from `tafsir_entries.output_tier`.

**Tech Stack:** Postgres 15 (Supabase), Deno (Edge Function), Python 3 (bot adapters), Telegram Bot API.

**Consensus source:** CAI-RESP-045 (strategic_decisions id 290, parent_ref=AL-BAYAN-001). C reframed as "minimum credibility bar for Al-Bayān as Muslim AI Scholar Brain". Output attribution is mandatory.

**Not in this plan (deferred):** Option A (topic_tags FTS + 20-query empirical beat), Option B (taxonomy expansion). Both are downstream of Phase 1 and scholar-gated.

---

## File Structure

| File | Change | Responsibility |
|------|--------|----------------|
| `supabase/migrations/20260419_001_search_tafsir_fts.sql` | Create | GIN index on `tafsir_entries.english_text`; RPC `search_tafsir_fts(query text, lim int)` joining `tafsir_entries` → `ayat` with ts_rank. |
| `supabase/functions/ask-scholar/index.ts` | Modify | Add `searchTafsirFTS()` DB function; insert new pipeline stage after ayat-FTS that merges tafsir-only matches; extend `MatchEntry.tafsir[]` with `matched_passage` + `matched_passage_tier` fields; update `buildSuccessResponse` tier-set accumulation. |
| `scripts/albayan_bot.py` | Modify | Render `matched_passage` with scholar-attributed tier marker when present. Keep existing ayat-first layout. |
| `scripts/mizan_bot.py` | Modify | Add direct `supabase_rpc("search_tafsir_fts", ...)` call as a fallback when `search_ayat_fts` returns empty; render with attribution. |
| `scripts/smoke_tafsir_fts.sh` | Create | Curl-based smoke harness: 5 hand-picked queries that should surface tafsir matches, run against deployed Edge Function. |
| `docs/superpowers/specs/2026-04-19-tafsir-fts-bot-funnel.md` | Create (optional) | Short spec summary if reviewers want one; CAI-RESP-045 body is sufficient. |

Each task ships its own commit. Tasks 1-2 are prerequisite; Tasks 3-4 can run in parallel once Task 2 ships; Task 5 is the final validation gate.

---

## Task 1: Postgres RPC `search_tafsir_fts` + GIN index

**Files:**
- Create: `supabase/migrations/20260419_001_search_tafsir_fts.sql`

- [ ] **Step 1: Write the migration SQL**

Create `supabase/migrations/20260419_001_search_tafsir_fts.sql`:

```sql
-- Phase 1 — Tafsir FTS RPC
-- Adds a GIN index on tafsir_entries.english_text and an RPC that
-- returns ayah-joined matches ranked by ts_rank. Excludes rows whose
-- english_text begins with "[Arabic tafsir" (no-translation placeholder).

CREATE INDEX IF NOT EXISTS idx_tafsir_entries_english_fts
  ON tafsir_entries
  USING GIN (to_tsvector('english', english_text));

CREATE OR REPLACE FUNCTION search_tafsir_fts(query text, lim int DEFAULT 5)
RETURNS TABLE (
  ayah_id              uuid,
  surah_number         int,
  ayah_number          int,
  arabic_text          text,
  english_translation  text,
  translator           text,
  scholar_name         text,
  source_work          text,
  english_text         text,
  output_tier          text,
  rank                 real
)
LANGUAGE sql
STABLE
AS $$
  SELECT
    a.id            AS ayah_id,
    a.surah_number,
    a.ayah_number,
    a.arabic_text,
    a.english_translation,
    a.translator,
    t.scholar_name,
    t.source_work,
    t.english_text,
    t.output_tier,
    ts_rank(
      to_tsvector('english', t.english_text),
      websearch_to_tsquery('english', query)
    ) AS rank
  FROM tafsir_entries t
  JOIN ayat a ON a.id = t.ayah_id
  WHERE to_tsvector('english', t.english_text)
        @@ websearch_to_tsquery('english', query)
    AND t.english_text NOT LIKE '[Arabic tafsir%'
  ORDER BY rank DESC
  LIMIT lim;
$$;

GRANT EXECUTE ON FUNCTION search_tafsir_fts(text, int) TO anon, authenticated;
```

- [ ] **Step 2: Apply migration to live Supabase**

Run via Supabase Management API (per the pattern used for migrations 003/004 in hifz). Project ref: `tscuymavysscrvoberrr`.

```bash
PGPASSWORD="$SUPABASE_DB_PASSWORD" psql \
  "postgresql://postgres.tscuymavysscrvoberrr:$SUPABASE_DB_PASSWORD@aws-0-ap-southeast-2.pooler.supabase.com:6543/postgres" \
  -f supabase/migrations/20260419_001_search_tafsir_fts.sql
```

Expected output: `CREATE INDEX` and `CREATE FUNCTION` + `GRANT` (no errors).

- [ ] **Step 3: Verify with a probe query**

```bash
PGPASSWORD="$SUPABASE_DB_PASSWORD" psql \
  "postgresql://postgres.tscuymavysscrvoberrr:$SUPABASE_DB_PASSWORD@aws-0-ap-southeast-2.pooler.supabase.com:6543/postgres" \
  -c "SELECT surah_number, ayah_number, scholar_name, LEFT(english_text, 80) AS excerpt, rank FROM search_tafsir_fts('patience trial', 3);"
```

Expected: 3 rows returned with `rank > 0`, all with non-null `scholar_name`, none starting with `[Arabic tafsir`.

- [ ] **Step 4: Commit**

```bash
cd /Users/sheikhmusa/wingmen/projects/ai-scholar
git add supabase/migrations/20260419_001_search_tafsir_fts.sql
git commit -m "feat(db): add search_tafsir_fts RPC + GIN index

Phase 1 of CAI-RESP-045 Option C — surface scholar-attributed tafsir
passages as a search funnel stage. GIN index on english_text with
websearch_to_tsquery; excludes Arabic-only placeholder rows."
```

---

## Task 2: Edge Function — `ask-scholar` wires tafsir FTS stage

**Files:**
- Modify: `supabase/functions/ask-scholar/index.ts:475-503` (add `searchTafsirFTS`), `:643-656` (extend `MatchEntry`), `:682-712` (tier accumulation), `:820-848` (stage 4 insertion)

- [ ] **Step 1: Add `TafsirFtsRow` interface and `searchTafsirFTS` DB helper**

Insert after `searchAyatILike` (line ~503):

```ts
interface TafsirFtsRow {
  ayah_id: string;
  surah_number: number;
  ayah_number: number;
  arabic_text: string;
  english_translation: string;
  translator: string;
  scholar_name: string;
  source_work: string;
  english_text: string;
  output_tier: string;
  rank: number;
}

/** Full-text search on tafsir_entries.english_text, ayah-joined */
async function searchTafsirFTS(
  query: string,
  limit = 5
): Promise<TafsirFtsRow[]> {
  const { data, error } = await supabase.rpc("search_tafsir_fts", {
    query,
    lim: limit,
  });
  if (error || !data || data.length === 0) return [];
  return data as TafsirFtsRow[];
}
```

- [ ] **Step 2: Extend `MatchEntry.tafsir[]` with matched-passage fields**

Edit the `MatchEntry` interface (line ~643):

```ts
interface MatchEntry {
  surah: number;
  ayah: number;
  surah_name: string;
  arabic: string;
  translation: string;
  translator: string;
  tafsir: {
    scholar: string;
    source: string;
    text: string;
    tier: string;
    matched_passage: string | null;       // NEW — FTS-matched excerpt (null if not from FTS)
    matched_passage_tier: string | null;  // NEW — tier marker for the matched passage
  }[];
}
```

- [ ] **Step 3: Add `buildMatchesFromTafsirFTS` builder**

Insert after `buildMatches` (line ~733):

```ts
/**
 * Build MatchEntry[] from tafsir-FTS results. Groups rows by ayah_id so one
 * ayah with multiple matching scholars produces a single MatchEntry with
 * multiple tafsir[] entries, each carrying a matched_passage.
 */
function buildMatchesFromTafsirFTS(rows: TafsirFtsRow[]): MatchEntry[] {
  const byAyah = new Map<string, MatchEntry>();
  for (const r of rows) {
    if (!byAyah.has(r.ayah_id)) {
      byAyah.set(r.ayah_id, {
        surah: r.surah_number,
        ayah: r.ayah_number,
        surah_name: getSurahName(r.surah_number),
        arabic: r.arabic_text,
        translation: r.english_translation,
        translator: r.translator,
        tafsir: [],
      });
    }
    byAyah.get(r.ayah_id)!.tafsir.push({
      scholar: r.scholar_name,
      source: r.source_work,
      text: r.english_text,
      tier: r.output_tier,
      matched_passage: r.english_text,    // Phase 1: pass full text; Phase 2 may add snippet highlighting
      matched_passage_tier: r.output_tier,
    });
  }
  return Array.from(byAyah.values());
}
```

- [ ] **Step 4: Insert tafsir-FTS stage after ayat-FTS in the main handler**

Edit the main handler (line ~820). Replace:

```ts
    // Stage 4: Full-text search on Quran ayat
    const joinedKeywords = keywords.join(" ");
    let ayat = await searchAyatFTS(joinedKeywords, 3);

    // ILIKE fallback if FTS returns nothing
    if (ayat.length === 0) {
      ayat = await searchAyatILike(keywords, 3);
    }
```

with:

```ts
    // Stage 4: Full-text search on Quran ayat
    const joinedKeywords = keywords.join(" ");
    let ayat = await searchAyatFTS(joinedKeywords, 3);

    // Stage 4b: Full-text search on tafsir commentary.
    // Runs unconditionally so strong tafsir matches can surface even when
    // ayat-FTS already returned results. Results are merged; tafsir-only
    // ayat (not already in `ayat`) are appended.
    const tafsirFtsRows = await searchTafsirFTS(joinedKeywords, 5);
    const tafsirMatches = buildMatchesFromTafsirFTS(tafsirFtsRows);

    // ILIKE fallback if BOTH FTS stages returned nothing
    if (ayat.length === 0 && tafsirMatches.length === 0) {
      ayat = await searchAyatILike(keywords, 3);
    }
```

- [ ] **Step 5: Merge tafsir-FTS matches into the final match set**

Still in the main handler, replace the final result block (line ~837):

```ts
    // Return combined results (Quran + Hadith)
    if (ayat.length > 0 || hadithMatches.length > 0) {
      const ayahIds = ayat.map((a) => a.id);
      const tafsirMap = ayat.length > 0 ? await fetchTafsirBatch(ayahIds) : {};
      const matches = buildMatches(ayat, tafsirMap);
      return new Response(
        JSON.stringify(buildSuccessResponse(rawQuery, matches, null, hadithMatches)),
        ...
      );
    }
```

with:

```ts
    // Return combined results (Quran + Tafsir-FTS + Hadith)
    if (ayat.length > 0 || tafsirMatches.length > 0 || hadithMatches.length > 0) {
      const ayahIds = ayat.map((a) => a.id);
      const tafsirMap = ayat.length > 0 ? await fetchTafsirBatch(ayahIds) : {};
      const ayatMatches = buildMatches(ayat, tafsirMap);

      // De-duplicate: skip tafsir-FTS matches for ayat already in ayatMatches
      const seenAyat = new Set(ayatMatches.map((m) => `${m.surah}:${m.ayah}`));
      const tafsirOnly = tafsirMatches.filter(
        (m) => !seenAyat.has(`${m.surah}:${m.ayah}`)
      );

      const matches = [...ayatMatches, ...tafsirOnly];
      return new Response(
        JSON.stringify(buildSuccessResponse(rawQuery, matches, null, hadithMatches)),
        {
          status: 200,
          headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
        }
      );
    }
```

- [ ] **Step 6: Update tier accumulation in `buildSuccessResponse`**

Edit `buildSuccessResponse` (line ~688):

```ts
  const tiersUsed = new Set<string>();
  for (const m of matches) {
    if (m.arabic) tiersUsed.add("quoted");  // Quoted is only for verbatim Quran text
    for (const t of m.tafsir) {
      tiersUsed.add(t.tier);
      if (t.matched_passage_tier) tiersUsed.add(t.matched_passage_tier);
    }
  }
```

- [ ] **Step 7: Deploy the Edge Function**

```bash
cd /Users/sheikhmusa/wingmen/projects/ai-scholar
supabase functions deploy ask-scholar --project-ref tscuymavysscrvoberrr
```

Expected output: `Deployed Function ask-scholar on project tscuymavysscrvoberrr`.

- [ ] **Step 8: Verify with a curl probe**

```bash
curl -s -X POST https://tscuymavysscrvoberrr.supabase.co/functions/v1/ask-scholar \
  -H "Authorization: Bearer $SUPABASE_ANON_KEY" \
  -H "Content-Type: application/json" \
  -d '{"question": "trials and tribulations"}' | jq '.matches[] | {surah, ayah, tafsir_count: (.tafsir | length), has_matched: (.tafsir | map(.matched_passage != null) | any)}'
```

Expected: at least one match where `has_matched: true` (i.e., a row whose tafsir passage was surfaced by FTS, not only by ayah-join).

- [ ] **Step 9: Commit**

```bash
cd /Users/sheikhmusa/wingmen/projects/ai-scholar
git add supabase/functions/ask-scholar/index.ts
git commit -m "feat(edge): wire search_tafsir_fts into ask-scholar pipeline

Stage 4b runs tafsir-FTS alongside ayat-FTS; results merged with
de-duplication by surah:ayah. Response adds matched_passage and
matched_passage_tier per tafsir entry, preserving AL-BAYAN-001
four-tier attribution through the funnel."
```

---

## Task 3: Albayan bot — rewrite `format_response` against actual Edge Function shape + render matched passages

**Known drift (discovered during plan authoring):** `scripts/albayan_bot.py:177-273` currently reads `data["status"]` and `data["response"]["arabic" | "translation" | "tafsir"]`, but the Edge Function (`supabase/functions/ask-scholar/index.ts:658-712`) actually returns `{question, scholar_gate, matches: [...], hadith_matches, practice_offramp, tiers_used}` — no `status`, no `response` envelope. Task 3 replaces `format_response` entirely. This is blocking for Phase 1: without it, the bot cannot surface anything, matched-passage or otherwise.

**Files:**
- Modify: `scripts/albayan_bot.py:177-273` (replace `format_response`)

- [ ] **Step 1: Replace `format_response` with a shape-correct implementation**

Overwrite the existing function (lines 177-273) with:

```python
def format_response(data):
    """Format the ask-scholar Edge Function JSON into a Telegram message.

    Edge Function response shape:
      { question, scholar_gate: bool, matches: [MatchEntry], hadith_matches: [...],
        practice_offramp: str, tiers_used: [str], message?: str, suggested_resources?: [str] }
    MatchEntry:
      { surah, ayah, surah_name, arabic, translation, translator,
        tafsir: [{ scholar, source, text, tier,
                   matched_passage, matched_passage_tier }] }
    """
    if data.get("error"):
        return ERROR_MESSAGE

    if data.get("scholar_gate"):
        return SCHOLAR_GATE_MESSAGE

    matches = data.get("matches") or []
    hadith_matches = data.get("hadith_matches") or []

    if not matches and not hadith_matches:
        return NO_MATCH_MESSAGE

    parts = ["--- Al-Bayan ---\n"]
    sources = []

    for m in matches:
        surah_num = m.get("surah", "")
        ayah_num = m.get("ayah", "")
        surah_name = m.get("surah_name", "")
        arabic = m.get("arabic", "")
        translation = m.get("translation", "")
        translator = m.get("translator", "")

        if arabic:
            parts.append(arabic)
            parts.append("")

        if translation:
            parts.append(f'"{translation}"')
            ref_bits = []
            if translator:
                ref_bits.append(translator)
            ref_bits.append(f"{surah_name} ({surah_num}:{ayah_num})" if surah_name else f"{surah_num}:{ayah_num}")
            parts.append(f"-- {', '.join(ref_bits)}")
            parts.append(f"[Quoted: Quran {surah_num}:{ayah_num}]")
            parts.append("")

        if surah_num and ayah_num:
            sources.append(f"Quran {surah_num}:{ayah_num}")

        tafsir_list = m.get("tafsir") or []
        if tafsir_list:
            parts.append("--- Tafsir ---\n")
            for t in tafsir_list:
                scholar = t.get("scholar", "Unknown")
                source = t.get("source", "")
                matched = t.get("matched_passage")
                if matched:
                    # FTS-surfaced passage — emit as "matched passage" with its own tier
                    tier = (t.get("matched_passage_tier") or "paraphrased").capitalize()
                    parts.append(f"{scholar} ({source}) — matched passage:")
                    parts.append(f'"{matched}"')
                    parts.append(f"[{tier}: {scholar}, {source}]")
                    parts.append("")
                else:
                    # Ayah-join tafsir (fetched by ayah_id, not FTS-surfaced)
                    text = t.get("text", "")
                    if not text or text.startswith("[Arabic tafsir"):
                        continue
                    tier = (t.get("tier") or "paraphrased").capitalize()
                    parts.append(f"{scholar} ({source}):")
                    parts.append(f'"{text}"')
                    parts.append(f"[{tier}: {scholar}]")
                    parts.append("")

                if source and source not in sources:
                    sources.append(source)

    if hadith_matches:
        parts.append("--- Hadith ---\n")
        for h in hadith_matches:
            coll = h.get("collection", "unknown")
            num = h.get("hadith_number", "")
            grading = h.get("grading") or ""
            narrator = h.get("narrator") or ""
            english = h.get("english", "")
            header_bits = [coll]
            if num:
                header_bits.append(f"#{num}")
            if grading:
                header_bits.append(grading)
            if narrator:
                header_bits.append(narrator)
            parts.append(f"{' · '.join(header_bits)}:")
            parts.append(f'"{english}"')
            parts.append(f"[Quoted: Hadith, {coll} #{num}]")
            parts.append("")

    practice = data.get("practice_offramp")
    if practice:
        parts.append("--- Practice ---\n")
        parts.append(practice)
        parts.append("")

    parts.append("---")
    if sources:
        parts.append(f"Sources: {', '.join(sources)}")
    parts.append(
        "Transparency: All content above is sourced. "
        "Tier markers [] indicate origin."
    )
    return "\n".join(parts)
```

- [ ] **Step 2: Manual smoke test against live Edge Function**

Start the bot locally against the deployed Edge Function:

```bash
cd /Users/sheikhmusa/wingmen/projects/ai-scholar
ALBAYAN_BOT_TOKEN=$ALBAYAN_BOT_TOKEN python3 scripts/albayan_bot.py
```

Send via Telegram three probes:

| Query | Expected |
|-------|----------|
| `trials and tribulations` | One+ match with `— matched passage:` block and `[Paraphrased: <scholar>, <source>]` |
| `2:255` | Verse-ref path works; arabic + translation + [Quoted: Quran 2:255] |
| `is pork halal` | Scholar Gate message returned verbatim |

If any block in any response is missing its tier marker, the rewrite is incomplete.

- [ ] **Step 3: Commit**

```bash
cd /Users/sheikhmusa/wingmen/projects/ai-scholar
git add scripts/albayan_bot.py
git commit -m "fix(albayan): rewrite format_response for actual Edge Function shape

Bot previously expected {status, response:{...}} envelope; Edge Function
returns {matches:[...]} directly. Rewrite renders matches + hadith_matches
+ practice_offramp with AL-BAYAN-001 tier markers on every block, and
emits matched_passage sections with [<Tier>: <scholar>, <source>] when
tafsir-FTS surfaces a passage. CAI-RESP-045 Phase 1 Task 3."
```

---

## Task 4: Mizan bot — add tafsir-FTS to Claude synthesis context

**Mizan's integration pattern (confirmed during plan authoring):** Mizan does NOT format a direct Telegram response from Supabase rows. It gathers data into a `context_parts` list of labeled JSON blobs (`QURAN SEARCH:`, `TAFSIR for X:Y`, `HADITH SEARCH`, etc.) at `scripts/mizan_bot.py:482-508`, then passes that as context to Claude CLI via `ask_claude(question, context, history)` at `scripts/mizan_bot.py:512-569`. Claude synthesizes the user-facing response under the prompt rules at lines 526-556, which already require tier badges (📖 Quoted / 📝 Paraphrased / 💭 AI-Generated). So the Mizan change is: (1) include `search_tafsir_fts` results as a new labeled context block, (2) no prompt edit needed because existing rules already enforce tier markers.

**Files:**
- Modify: `scripts/mizan_bot.py` — add `search_tafsir` helper, insert context block in the FTS section

- [ ] **Step 1: Add `search_tafsir` helper after `search_quran` (after line 208)**

Insert:

```python
def search_tafsir(keywords, limit=5):
    """Full-text search on tafsir_entries.english_text, ayah-joined.
    Returns rows already grouped by ayah_id so one ayah with N matching
    scholars yields one entry with a matched[] list.
    """
    try:
        rows = supabase_rpc("search_tafsir_fts", {"query": keywords, "lim": min(limit, 10)})
    except Exception:
        return {"results": []}
    if not rows:
        return {"results": []}

    by_ayah = {}
    for r in rows:
        aid = r["ayah_id"]
        if aid not in by_ayah:
            by_ayah[aid] = {
                "surah": r["surah_number"],
                "ayah": r["ayah_number"],
                "surah_name": SURAH_NAMES.get(r["surah_number"], ""),
                "arabic": r["arabic_text"],
                "translation": r["english_translation"],
                "matched": [],
            }
        by_ayah[aid]["matched"].append({
            "scholar": r["scholar_name"],
            "source": r["source_work"],
            "passage": r["english_text"],
            "tier": r["output_tier"],
        })
    return {"results": list(by_ayah.values())}
```

- [ ] **Step 2: Insert tafsir-FTS context block in the FTS section (after line 497)**

Immediately after the existing Quran-FTS block (the one that appends `TAFSIR for X:Y` for the top Quran result), add:

```python
        # Tafsir FTS — surface scholar-attributed passages that matched the query
        # directly. Runs even when Quran FTS succeeded, because tafsir may add
        # signal (e.g., the matched passage addresses the query more directly
        # than the ayah translation).
        if _ctx_size(context_parts) < MAX_CONTEXT:
            tdata = search_tafsir(fts_query, limit=3)
            if tdata["results"]:
                context_parts.append(
                    f"TAFSIR MATCHED PASSAGES (scholar-attributed, from tafsir_entries FTS):\n"
                    f"{json.dumps(tdata, ensure_ascii=False, indent=2)}"
                )
```

- [ ] **Step 3: Verify Claude's prompt already covers matched-passage attribution**

Read `scripts/mizan_bot.py:534-555`. Confirm the RULES and FORMATTING sections already say "Use ONLY the provided data" and enforce tier badges. If those lines have changed, append a one-line clarifier:

```
- For TAFSIR MATCHED PASSAGES, attribute with the scholar name and source_work, and use 📝 (Paraphrased) unless tier == "quoted".
```

Do not rewrite the prompt. Just confirm or append that one line.

- [ ] **Step 4: Manual smoke test**

```bash
cd /Users/sheikhmusa/wingmen/projects/ai-scholar
MIZAN_BOT_TOKEN=$MIZAN_BOT_TOKEN python3 scripts/mizan_bot.py
```

Send via Telegram: `what does ibn kathir say about the trials of believers`. Expected: Claude's response cites Ibn Kathir by name with a 📝 badge on the quoted passage and a surah:ayah reference. If the response has no tier badges, the prompt rules regressed — check line 543-546.

- [ ] **Step 5: Commit**

```bash
cd /Users/sheikhmusa/wingmen/projects/ai-scholar
git add scripts/mizan_bot.py
git commit -m "feat(mizan): add tafsir-FTS context block for Claude synthesis

search_tafsir() calls search_tafsir_fts RPC and groups by ayah_id.
Results appended to context_parts as TAFSIR MATCHED PASSAGES block.
Existing Claude prompt rules (📖/📝/💭 tier badges) already enforce
AL-BAYAN-001 attribution. CAI-RESP-045 Phase 1 Task 4."
```

---

## Task 5: Deploy + smoke verification

**Files:**
- Create: `scripts/smoke_tafsir_fts.sh`

- [ ] **Step 1: Write the smoke harness**

Create `scripts/smoke_tafsir_fts.sh`:

```bash
#!/usr/bin/env bash
# Phase 1 smoke — 5 queries that should surface tafsir-FTS matches
# Usage: SUPABASE_ANON_KEY=... ./scripts/smoke_tafsir_fts.sh
set -euo pipefail

URL="https://tscuymavysscrvoberrr.supabase.co/functions/v1/ask-scholar"
: "${SUPABASE_ANON_KEY:?SUPABASE_ANON_KEY is required}"

QUERIES=(
  "trials and tribulations"
  "ibn kathir patience"
  "gratitude to allah"
  "what is tawakkul"
  "meaning of tawhid"
)

pass=0
fail=0
for q in "${QUERIES[@]}"; do
  resp=$(curl -s -X POST "$URL" \
    -H "Authorization: Bearer $SUPABASE_ANON_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"question\": \"$q\"}")
  has_matched=$(echo "$resp" | jq -r '[.matches[]?.tafsir[]? | select(.matched_passage != null)] | length')
  total_tafsir=$(echo "$resp" | jq -r '[.matches[]?.tafsir[]?] | length')
  if [ "$has_matched" -gt 0 ]; then
    echo "PASS  [$q] matched_passages=$has_matched total_tafsir=$total_tafsir"
    pass=$((pass+1))
  else
    echo "FAIL  [$q] no matched_passage surfaced"
    fail=$((fail+1))
  fi
done

echo "---"
echo "Passed: $pass / ${#QUERIES[@]}"
[ "$fail" -eq 0 ]
```

- [ ] **Step 2: Make it executable and run**

```bash
cd /Users/sheikhmusa/wingmen/projects/ai-scholar
chmod +x scripts/smoke_tafsir_fts.sh
SUPABASE_ANON_KEY=$SUPABASE_ANON_KEY ./scripts/smoke_tafsir_fts.sh
```

Expected: at least 4 of 5 queries PASS. If fewer pass, inspect which queries fail — the FTS tokenization may be dropping a key term. Do not tune the query set to hide failures; document the failures in the commit message.

- [ ] **Step 3: Restart the Mizan bot on the Mac Mini**

Confirmed live supervision state: `~/Library/LaunchAgents/dev.wingmen.mizan-bot.plist` exists and is running (PID was 69500 at plan authoring). There is NO `dev.wingmen.albayan-bot.plist` — Albayan is not currently under launchd supervision.

Restart Mizan per the BUG-016 safe-restart procedure (`launchctl kickstart`, never `nohup`):

```bash
launchctl kickstart -k gui/$(id -u)/dev.wingmen.mizan-bot
# Verify restart:
launchctl list | grep dev.wingmen.mizan-bot
ps aux | grep mizan_bot.py | grep -v grep
```

Expected: `launchctl list` shows a non-zero PID for `dev.wingmen.mizan-bot`, `ps` shows one `mizan_bot.py` process whose start time is within the last minute.

**Albayan runtime — flagged for post-Phase-1 follow-up:** Ship the Albayan code change in this plan but do NOT block the Phase 1 Definition of Done on an Albayan live deployment. Filing the Albayan launchd plist is a separate piece of work (candidate TASK-NNN: "add dev.wingmen.albayan-bot.plist to LaunchAgents"). For Phase 1 smoke, the implementer runs Albayan locally in Step 4 of this task to confirm the rewrite works end-to-end.

- [ ] **Step 4: Live Telegram smoke**

**Mizan (live, under launchd):** send to @mzninterfacebot:
1. `what does ibn kathir say about the trials of believers` — Claude response cites Ibn Kathir with 📝 badge
2. `2:255` — verse-ref path, Arabic + 📖 badge
3. `gratitude` — topic match, no regression
4. `is pork halal` — scholar gate / redirect, no regression

**Albayan (local, run from terminal for this smoke):**

```bash
cd /Users/sheikhmusa/wingmen/projects/ai-scholar
ALBAYAN_BOT_TOKEN=$ALBAYAN_BOT_TOKEN python3 scripts/albayan_bot.py
```

Then send to @AlBayanBot:
1. `trials and tribulations` — matched_passage block with `[Paraphrased: <scholar>, <source>]`
2. `2:255` — verse-ref path, `[Quoted: Quran 2:255]`
3. `is pork halal` — `SCHOLAR_GATE_MESSAGE` returned verbatim

Every tafsir block in every Albayan response must carry a `[Quoted|Paraphrased|Inferred: <scholar>[, <source>]]` marker. Mizan responses must carry 📖/📝/💭 badges. If any block is missing a marker, Task 3 or Task 4 is incomplete — return to that task and fix before continuing.

- [ ] **Step 5: Commit the smoke harness**

```bash
cd /Users/sheikhmusa/wingmen/projects/ai-scholar
git add scripts/smoke_tafsir_fts.sh
git commit -m "test(phase1): smoke harness for tafsir-FTS bot funnel

5 queries with matched_passage expectations. Part of CAI-RESP-045
Phase 1 validation gate before handing off to Phase 2 empirical beat."
```

- [ ] **Step 6: Post session digest to CAI**

Follow the session digest routine (see user's feedback_session_digest memory). Insert an `agent_messages` row with `to_agent='cai'`, `message_type='update'`, `requires_response=false` summarizing: migrations applied, edge function deployed, bots restarted, smoke results. Reference `parent_ref='CAI-RESP-045'`.

---

## Definition of Done

- `search_tafsir_fts` RPC deployed, verified via psql probe
- Edge Function deployed with tafsir-FTS stage merged into pipeline
- Both bots render matched_passage blocks with mandatory AL-BAYAN-001 tier markers
- `scripts/smoke_tafsir_fts.sh` passes ≥4 / 5 queries
- Live Telegram smoke passes all 5 hand-checks (3 new, 2 regression)
- Session digest posted to CAI referencing CAI-RESP-045

## Out of Scope (Phase 2+)

- Wiring the 2423 populated `topic_tags` into FTS (Option A step 1)
- 20-query empirical beat comparing old FTS vs new tafsir FTS vs topic-tag FTS (Option A decision gate)
- Finishing the remaining 3813 tag enrichments (gated on Option A beat result)
- Taxonomy expansion (Option B) — scholar-gated, file as AL-BAYAN-002 separately
- Migration from Max plan to API plane (ARCH-031 dependency, handled in that plan)

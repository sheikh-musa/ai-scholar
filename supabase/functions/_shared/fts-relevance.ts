// FTS relevance floor (coverage-based) — #6489.
//
// ts_rank is NOT a usable cross-query floor: a legit "gratitude" hit
// (ts_rank 0.061) can rank below off-topic "prevent"->"prevent death" noise
// (0.087), because ts_rank scales with term-frequency/doc-length, not
// topicality. The OR-joined keyword FTS + the per-keyword ILIKE fallback
// therefore surface a passage that hit a single GENERIC word while the
// distinctive query terms matched nothing (the eyelash->Al-'Imran 3:168
// "prevent death" miss). Coverage IS separable: keep a hit only if the matched
// text carries a distinctive (non-generic) query term, or >= 2 query terms.
// Prefix match (5 chars) absorbs FTS stemming (extensions->extension).
//
// Extracted from ask-scholar/index.ts so the floor is unit-testable in Deno
// without importing index.ts (which starts Deno.serve at module load). Kept in
// lockstep with the Python port in scripts/mizan_bot.py (_fts_topical).

export const FTS_GENERIC = new Set([
  "prevent", "prevents", "prevented", "make", "makes", "made", "making",
  "give", "gives", "given", "giving", "take", "takes", "taken", "taking",
  "use", "uses", "used", "using", "get", "gets", "got", "getting", "keep",
  "keeps", "kept", "put", "puts", "come", "comes", "came", "want", "wants",
  "wanted", "need", "needs", "needed", "help", "helps", "tell", "tells",
  "told", "ask", "asks", "asked", "say", "says", "said", "know", "knows",
  "known", "thing", "things", "way", "ways", "time", "times", "people",
  "person", "find", "finds", "found", "show", "shows", "showed", "work",
  "works", "good", "bad", "many", "much", "more", "most", "some", "between",
]);

/**
 * True if an FTS-matched `text` genuinely covers the query — it contains a
 * distinctive (non-generic) query term, or >= 2 query terms. Returns true when
 * there is nothing to check against, so it never over-filters.
 */
export function ftsTopical(queryWords: string[], text: string): boolean {
  const tl = (text || "").toLowerCase();
  const content = queryWords.filter((w) => w.length >= 3);
  if (content.length === 0) return true;
  const distinctive = content.filter((w) => !FTS_GENERIC.has(w));
  if (distinctive.some((w) => tl.includes(w.slice(0, 5)))) return true;
  return content.filter((w) => tl.includes(w.slice(0, 5))).length >= 2;
}

# Bayan hadith-collection resolver — redesign notes (op#6457 → op#6474 → op#10273)

**Status:** ✅ SHIPPED 2026-08-04 (op#10273, "manage the bot"). The deferred
redesign below was implemented as designed: a deterministic transliteration-folding
resolver (`_translit_key` + `_COLLECTION_SIGNATURES` + `_resolve_collection_token`
in `scripts/mizan_bot.py`) replaced the hard-coded alias alternation for
numbered-hadith lookup; the alias dict is retained only as a fallback for multi-word
English titles. 34/34 unit cases pass (daud family, all 8 collections + variants,
guards held, adversarial no-match stays None); `eval_retrieval.py --gate` = 140/140
PASS, 0 BAD (added `sunan abi daud 2162` + `abu daoud 2162` regression rows);
live in-process verify against prod returned Abu Dawud #2162 for the `daud`/`daoud`
spellings. No LLM in the resolution path (tafsir-defense-funnel F-1 preserved).

---

**Original status (2026-07-23):** DEFERRED by operator. Nothing shipped at the time
(the band-aid alias edits described below were made, verified, then reverted). Focus
shifted to irsyad. This file was the handoff for whoever picked it up.

## The trigger

`"sunan abi daud 2162"` → not-found, while `"sunan abi dawud 2162"` → correct hadith.
Same hadith #2162, same corpus; only difference is the transliteration **daud vs dawud**.
Repro from `mizan_interactions`: FAIL id `cb7e6afe-c1b4-4c57-98da-9213f1464cae`,
PASS id `f0f2625a-deef-49b1-b2c2-d439d4b6d433`.

## Root cause (confirmed in code)

Numbered-hadith lookup resolves the collection via a **hard-coded alias dict**
`HADITH_COLLECTION_ALIASES` (`scripts/mizan_bot.py:761`), consumed by
`parse_numbered_hadith()` (`~:837`, longest-alias-wins `str.find` scan). Both call
sites — `gather_context` (`~:2041`) and the direct-answer path (`~:2697`) — run
`parse_numbered_hadith` FIRST, then fall back to a legacy token regex
(`~:2048`, `~:2703`) that only knows `abudawud|abu dawud|...`. So the alias dict is
effectively the single resolver.

The dict listed only `dawud`/`dawood` spellings for داود, never the no-'w' `daud`/`daoud`.
So `"...abi daud 2162"` matched no alias → number 2162 never scoped to a collection →
semantic fallback → miss.

**The guard to preserve** (`parse_numbered_hadith` docstring, `~:848`): the number must
FOLLOW the collection name (optionally after `# : . , - no. hadith`). A bare number
elsewhere is ignored, so `"abu dawud on the 5 pillars"` must NOT resolve to Abu Dawud #5.
Verified this still holds under the band-aid.

## Why the operator rejected the band-aid

Adding `daud`/`daoud`/`dawood`/`abudaud`… as dict entries is whack-a-mole: every new
transliteration a user invents (`dawuud`, `daawood`, `tirmizhi`, `an nasaai`, …) is
another not-found until someone hand-adds it. It's a broken design — the resolver should
**normalize any reasonable transliteration to the canonical collection**, not enumerate
permutations. Do not resurrect the permutation list as the fix.

## What I verified before stopping (so it isn't lost)

- The permutation patch (adding daud/daoud/dawood variants + a few others) DID make
  `parse_numbered_hadith` resolve all of: `sunan abi daud 2162`, `sunan abu daud 2162`,
  `abu daoud 2162`, `tirmidzi 100`, `nasa'i 55`, `ibn maja 10` → correct collection_id +
  number, and STILL returned `None` for `abu dawud on the 5 pillars` (guard intact).
  This confirms the *resolution point* is correct; only the *matching strategy* is wrong.
- Corpus truly has Abu Dawud #2162 (the PASS interaction returned it). So this is purely
  a resolver-coverage bug, not missing data.
- `scripts/eval_retrieval.py` already carries a pinned regression case for
  `"sunan abi dawud 2162"` (op#6158, `expect_contains: [abudawud, 2162, accursed]`).
  A real fix should add the `daud` spelling (and a couple of adversarial transliterations)
  as regression rows there and run `python3 scripts/eval_retrieval.py --gate` green.
  NOTE: the gate hits Supabase and, in FAST mode, still takes a while; stdout is buffered
  (not a tty) so nothing prints until it finishes — don't assume it hung.

## Proposed real fix — a normalized collection resolver (sketch, deterministic)

The candidate set is CLOSED and tiny (~9 collections). That makes a deterministic
normalize-then-match resolver both robust and cheap — and it keeps the LLM out of the
hot path (respects the tafsir-defense-funnel / retrieval-first invariant; no synthesis
call to classify a collection name).

**Shape:** replace the alias dict + `parse_numbered_hadith`'s `str.find` scan with:

1. `normalize_translit(s)` — fold a string to a transliteration-invariant key:
   - lowercase; NFKD; strip combining marks, apostrophes/hamza (`'ʿʾ`), hyphens.
   - drop leading articles/titles: `al-|an-|at-|ash-|sunan|sahih|jami|imam|musnad`.
   - drop the genitive/kunya carrier so `abi`≈`abu` (both → `ab`), and the `sunan abi/abu`
     prefix collapses.
   - phonetic folds tuned for Arabic→Latin variance:
     `w`→∅ between vowels (dawud/daud→`daud`), `oo`→`u`, `ee`→`i`, `dh|dz|z`→`d`
     (tirmidhi/tirmidzi/tirmizi→`tirmidi`), `kh`→`k`, `aa`→`a`, `th`→`t`, double→single,
     trailing `h`→∅ (majah/maja→`maja`).
   - collapse whitespace.
   Precompute this key ONCE for each canonical collection name (and 1–2 well-known
   English titles, e.g. "gardens of the righteous").

2. `resolve_collection(phrase)` — compute `normalize_translit(phrase)`, compare against
   the ~9 canonical keys. Exact key hit → return. Else best match by normalized
   Levenshtein ratio (or token-set overlap) ABOVE a conservative threshold (e.g. ≥0.85
   AND the phrase actually contains a distinctive collection token, to avoid stealing
   generic words). Below threshold → `None` (honest not-found, never a wrong collection).

3. `parse_numbered_hadith(text)` — keep the current "number must follow the collection
   span, bare number elsewhere ignored" GUARD. But instead of `str.find` over a permutation
   dict, slide `resolve_collection` over the pre-number span. Concretely: find the number
   anchor first, take the ≤4 preceding tokens as the candidate collection phrase, resolve
   that. This preserves the `"abu dawud on the 5 pillars"` guard (the tokens before "5"
   are "on the", which resolve to nothing) AND is spelling-agnostic.

**Tests to lock it (must all pass, plus the guard):**
- `daud/dawud/dawood/daoud/dawuud` × `{sunan abi, sunan abu, abu, abi, bare}` + N → Abu Dawud.
- `tirmidhi/tirmidzi/tirmizi/tirmithi`, `nasai/nasa'i/nasaai/an nasai`, `majah/maja`,
  `bukhari/bukhaari`, `muslim`, `ibn majah/ibn maja` → each canonical id.
- GUARD (must stay `None`): `abu dawud on the 5 pillars`, `the 5 daily prayers`,
  `bukhari and muslim both narrate` (no number), a random surah:ayah like `2:255`.
- Adversarial no-match (must be `None`, not a wrong-collection false positive):
  `mahmud 12`, `daudi bohra 3`, `imam ahmad 5` (Musnad Ahmad — NOT in the 9; confirm it
  stays not-found rather than snapping to the nearest key).

**Watch-outs:**
- `w`→∅ folding is aggressive; make sure it doesn't collide two distinct collections into
  the same key. With only 9 targets, verify the key set is still injective after folding.
- Threshold tuning: too loose and `muslim`↔`musnad`, `nasai`↔`nawawi` could collide. Test
  the full 9×9 confusability matrix, not just the happy path.
- Keep it in ONE place (the resolver) — the two legacy regexes at `~:2048`/`~:2703` should
  then be deletable, or kept only as a trivial safety net. One repo, zero forks.
- Do NOT route collection-name classification through an LLM before retrieval (funnel
  violation). Deterministic normalizer only.

## Pointers

- `scripts/mizan_bot.py:761` `HADITH_COLLECTION_ALIASES` — the dict to replace.
- `scripts/mizan_bot.py:837` `parse_numbered_hadith` — resolver + number-anchor guard.
- `scripts/mizan_bot.py:2041,2697` — the two call sites (both alias-first already).
- `scripts/mizan_bot.py:2048,2703` — legacy token regexes (safety-net fallback).
- `scripts/eval_retrieval.py` + `scripts/eval_retrieval_queries.json` — the gate to extend.
- Brief: `~/wingmen/orchestrator/reports/bayan-daud-fix-brief-20260723.md` (op#6457).
- Prior related fix: commit `617fec1` (op#6158, added the `abi` genitive spellings).

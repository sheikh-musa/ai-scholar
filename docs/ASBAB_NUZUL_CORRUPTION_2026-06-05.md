# Asbāb al-Nuzūl source-tag corruption — diagnostic findings

**Filed:** 2026-06-05 by cc-scholar
**Status:** Documented, awaiting cleanup window (not in-flight; Quduri ingestion in progress simultaneously)

## Finding

`public.asbab_nuzul` has **1,187 rows** total. **902 are tagged `source = "al-wahidi"`** — purportedly Al-Wahidi's classical *Asbāb al-Nuzūl* (d. 468 AH, strict historical-occasion catalogue with isnāds).

**At least 174 of those 902 rows (~19%) contain content that is unambiguously ishārī (Sufi-allegorical) tafsir, NOT historical asbāb.** They cite "the Pir of the Tariqah", reference "the recognizer", invoke "the wayfarer" — the standard vocabulary of Maybudī's *Kashf al-Asrār* (d. 520 AH), the well-known ishārī commentary that classically *interleaves* with al-Wahidi's text in some editions.

## Evidence — ishārī markers in al-wahidi-tagged rows

| ishārī phrase | rows tagged al-wahidi |
|---|---|
| "tariqah" (Sufi path) | **174** |
| "Pir of the Tariqah" (Sufi master title) | **134** |
| "the recognizer" (gnostic ʿārif) | **100** |
| "the lover" (allegorical) | **35** |
| "the wayfarer" (sālik) | **17** |
| "in terms of allusion" (ishārī formula) | **17** |
| "the road to" (allegorical path) | **20** |

Compare to genuine-asbāb markers in the SAME al-wahidi-tagged set:
| asbāb phrase | rows |
|---|---|
| "This verse was revealed" | 136 |
| "When the Messenger" | 41 |
| "the hypocrites" | 41 |
| "Quraysh" | 82 |

So the corpus contains BOTH genuine asbāb material AND ishārī material — under the same `source = "al-wahidi"` label. Attribution is corrupted.

## Concrete example (id=590, Surah 10:5)

```
source: al-wahidi
text_en: "He it is who made the sun a radiance and the moon a light. In terms
of allusion, this sun is the sun of success-giving, which shines from the
constellation of solicitude on the servant's bodily parts so that they will
be adorned with service and obedience. The moon alludes to the light of
tawḥīd and the brightness of recognition in the heart of the recognizer,
for with this light he takes the road to the Recognized. The Pir of the
Tariqah said..."
```

This is **Maybudī's Kashf al-Asrār** in style and vocabulary — almost certainly that work's ishārī commentary on Q 10:5, NOT al-Wahidi's strict historical asbāb. (Al-Wahidi has nothing recorded for 10:5; the verse has no firmly-established *sabab nuzūl*.)

## Impact on user-facing answers

When the bot retrieves an asbab row for a tafsir query, it cites `source: al-wahidi`. For mislabeled rows, this is:

- **Misattribution** — quoting Maybudī's voice but crediting al-Wahidi.
- **Tier-integrity breach** — the answer is presented as `📝 paraphrased` from a named scholar, but the named scholar didn't write it.
- **Methodological confusion for the user** — al-Wahidi is *muḥaddith* methodology; Maybudī is *taṣawwuf* methodology. Mixing them under one label suggests an equivalence that doesn't exist.

## Proposed cleanup plan (for future window)

**Option A — Re-tag (recommended, low risk):**
1. Identify rows by ishārī-marker heuristic (the 7 phrases above + a few additional patterns).
2. Re-tag matched rows: `source = "maybudi-kashf-asrar"` (or "ishari-tafsir-uncertain-provenance" if Maybudī attribution itself can't be verified).
3. Keep the text — it has scholarly value, just under correct attribution.
4. ~250-300 rows expected to re-tag (counting overlap between heuristic markers).

**Option B — Re-ingest clean al-Wahidi:**
1. Source from OpenITI (al-Wāḥidī's *Asbāb al-Nuzūl* should be available there).
2. Replace al-wahidi-tagged rows with clean material.
3. Bigger lift but produces a clean classical corpus.

**Recommended order:** Do Option A first (~3h, reversible). Decide on Option B after observing whether re-tagged Maybudī content is actually being retrieved usefully.

**Out of scope for this finding:** the OTHER 902-174=728 al-wahidi-tagged rows. They may also have mislabels (different patterns), but the 174 with clear ishārī markers are the high-confidence subset.

## What is NOT broken

- Quranic text — KFGQPC canonical (Q-1 invariant holds).
- Hadith corpus — verified clean.
- Tafsir entries — separate table, separate sources, not affected by this corruption.
- The asbab schema itself — table structure is fine; only the source-tag values are wrong on a subset of rows.

## References

- Surfaced during retrieval-debugging earlier in cc-scholar session 2026-05-21 (id=590 spot-check on Q 10:5).
- Re-confirmed quantitatively 2026-06-05 via SQL pattern-match.
- Will close as part of asbab-cleanup task when a 3-hour focused window opens.

// Tests for the coverage-based FTS relevance floor (#6489). Run with `deno test`.
// Kept in lockstep with the Python port (scripts/test_fts_relevance_floor.py):
// the two implementations MUST agree, so these mirror the same cases.

import { assertEquals } from "https://deno.land/std@0.208.0/assert/mod.ts";
import { ftsTopical } from "../fts-relevance.ts";

// [queryWords, text, expectedKeep, label]
const cases: Array<[string[], string, boolean, string]> = [
  // The canonical bug: matched Al-'Imran 3:168 ("...prevent death...") on the
  // generic word "prevent" alone.
  [["eyelash", "extensions", "prevent", "wudhu"],
   "Do not think those slain for Allah are dead. They prevent the death of the soul.",
   false, "generic-only overlap is dropped"],
  [["prevent"], "they prevent death", false, "single generic word dropped"],
  [["riba"], "Those who consume riba will not stand.", true, "distinctive term kept"],
  [["combining", "prayers", "travelling"],
   "The traveller may combine the prayers while travelling on a journey.",
   true, ">=2 content terms kept"],
  [["praying"], "the manner of praying in congregation", true, "prefix absorbs stem"],
  [["extensions"], "hair extension rulings", true, "extensions->extension prefix"],
  [[], "anything at all", true, "empty query never over-filters"],
  [["to", "is", "of"], "short stopwords only", true, "all <3 chars kept"],
  [["riba"], "", false, "no text to cover -> not topical"],
  // DOCUMENTED prefix-5 limitation: "gratitude" ("grati") != "grateful" ("grate").
  [["gratitude"], "be grateful to Me and do not deny Me", false,
   "prefix-5 stem divergence dropped (known limitation)"],
  [["gratitude"], "this ayah is about gratitude to Allah", true,
   "exact form kept"],
];

for (const [words, text, expected, label] of cases) {
  Deno.test(`ftsTopical: ${label}`, () => {
    assertEquals(ftsTopical(words, text), expected);
  });
}

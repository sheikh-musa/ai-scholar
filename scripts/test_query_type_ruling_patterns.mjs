// Proof harness for cc-scholar 40-answer self-review Fix #3 (msg #10510):
// first-person / mubtilat / intimacy ruling-class queries must classify as
// 'ruling' so the INV-6 action_prompt + F-3 scholar-gate fire STRUCTURALLY,
// not just in the model's prose.
//
// Run: node scripts/test_query_type_ruling_patterns.mjs
// (Node >=23.6 strips the .ts types natively; deno not required locally.)
import { classifyQueryType } from "../supabase/functions/_shared/query-type-classifier.ts";

let pass = 0, fail = 0;
function expect(q, want) {
  const got = classifyQueryType(q).type;
  const ok = got === want;
  console.log(`${ok ? "PASS" : "FAIL"}  want=${want.padEnd(10)} got=${got.padEnd(10)}  ${q}`);
  ok ? pass++ : fail++;
}

console.log("--- ruling-class queries mis-classified in the 40-answer review (must now be 'ruling') ---");
expect("can i prey non stop", "ruling");                                                  // #13/#14
expect("is my asar prayed 5 minutes before maghrib azan valid?", "ruling");               // #02
expect("do eyelash extensions prevent wudhu", "ruling");                                   // #15
expect("if i masbuk the friday prayer in tashahud do i pray 2 rakaats or 4", "ruling");   // #19
expect("what are the intimacy limits with my wife when she is on her period", "ruling");  // #35
expect("does it nullify my fast to hold a non mahram's hands", "ruling");                  // #37
expect("can i pray sunnah prayers and jama' qasr prayers in congregation?", "ruling");     // #01 (already ruling — regression guard)

console.log("\n--- regression: legitimate non-ruling queries must NOT be dragged into 'ruling' ---");
expect("What does al fateha mean?", "definition");                     // #08/#09
expect("What is tasawwuf?", "definition");                             // #29
expect("What are the names of Rasullullah's wives?", "definition");    // #23
expect("how do i be the best husband and stepfather?", "other");       // #40 (has 'husband' but no intimacy trigger)
// #16 — was 'other' on the fix branch, but the integration UNION with main's
// #6489 retrieval work (RULING_PHRASES block (d): permissibility-defining
// consumables) deliberately routes donkey-meat consumption to 'ruling' so the
// F-3 scholar-gate fires. Over-gating a permissibility query is the safe
// direction for a scholar bot; assertion updated to match the merged classifier.
expect("hadith on eating donkey meat", "ruling");                       // #16 (reclassified by union)
expect("What hadiths were narrated by Ja'far R.A", "other");           // #22
expect("What are the Hadiths which instructs on how we take wudhu?", "definition"); // #20/#21 (already 'definition' in stored data; has 'wudhu' but no mubtilat trigger — unchanged by Fix #3)

console.log(`\n${fail === 0 ? "ALL PASS" : "FAILURES PRESENT"}: ${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);

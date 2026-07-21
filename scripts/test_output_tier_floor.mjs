// Proof harness for cc-scholar 40-answer self-review Fix #4 (msg #10510):
// output_tier must record the FLOOR (most-synthetic tier present) on mixed
// bodies, so a response that quotes an ayah but also surfaces an AI-translated
// matn is persisted 'ai-generated', not 'quoted'. 4-tier-transparency T-3.
//
// Run: node scripts/test_output_tier_floor.mjs
import { inferOutputTier } from "../supabase/functions/_shared/output-tier.ts";

let pass = 0, fail = 0;
function expect(label, body, want) {
  const got = inferOutputTier(body);
  const ok = got === want;
  console.log(`${ok ? "PASS" : "FAIL"}  want=${want.padEnd(13)} got=${got.padEnd(13)}  ${label}`);
  ok ? pass++ : fail++;
}

// Pure tiers
expect("pure quoted (only 📖 ayah/hadith)", "📖 *(Bukhari #4218)* the Prophet forbade donkey meat.", "quoted");
expect("pure paraphrased (only 📝)", "📝 Ibn Kathir explains this ayah refers to Qasr.", "paraphrased");
expect("plain conversational (no badge)", "Wa alaykum salam! How can I help you today?", "ai-generated");

// FLOOR on mixed bodies — the regressions the review caught:
expect("📖 + 💭 emoji → floor ai-generated", "📖 verse text\n💭 my own framing of it", "ai-generated");
expect("📖 + 📝 (no synthesis) → floor paraphrased", "📖 hadith\n📝 Ibn Kathir paraphrase", "paraphrased");
// #35-shape: has 📖 (quoted hadith) + 📝 (paraphrased tafsir) BUT the matn is an
// AI machine-translation labelled in PROSE without the 💭 emoji — the exact case
// the old emoji-only heuristic mis-tagged 'quoted'.
expect(
  "#35-shape: quoted+paraphrased + AI-translated matn in prose (no 💭)",
  "📖 *(Abu Dawud #264)* sahih\n📝 Al-Qurtubi: only intercourse is prohibited.\n" +
    "> Nihāyat al-Zayn (auto-translated from OpenITI; tier: AI-generated translation)",
  "ai-generated",
);
// #02-shape: paraphrased Ibn Kathir + Mukhtaṣar al-Qudūrī via Claude-sonnet auto-translation.
expect(
  "#02-shape: paraphrased + Claude-sonnet auto-translation matn",
  "📝 Ibn Kathir on prayer times.\n> Mukhtaṣar al-Qudūrī (AI translation via OpenITI, Claude Sonnet cli 2026-06-05)",
  "ai-generated",
);

console.log(`\n${fail === 0 ? "ALL PASS" : "FAILURES PRESENT"}: ${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);

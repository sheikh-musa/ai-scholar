# AI Scholar — NORTH STAR & Wingmen Nervous System

Two complementary systems under active specification by Gazzabyte. **NORTH STAR (Al-Bayan)** is an Islamic knowledge reasoning engine designed to connect people to their fitrah — their innate nature — through logic and mercy. It enforces a four-tier transparency model on every output (Quoted, Paraphrased, Inferred, AI-Generated), gates all fiqh rulings through verified scholarly sources, and offers a practice off-ramp at every session so users can move from knowledge to action. **Wingmen Nervous System** is the operational orchestration layer that keeps Claude Code (Telegram) and claude.ai aware of all Gazzabyte operations, powered by 3 Supabase tables, 4 scheduled tasks, and 5 tools.

Both systems are specification-complete. No code has been written yet.

---

## Directory Structure

```
ai-scholar/
  README.md
  north-star/
    NORTH_STAR_SCHOLAR_BRAIN.md        — Vision & philosophy
    PHASE_1_IMPLEMENTATION.md          — Technical spec for 10-ayat PoC
    SAMPLE_INTERACTIONS.md             — Example conversations
  wingmen/
    WINGMEN_NERVOUS_SYSTEM_SPEC_v2.md  — Full system architecture
    GLOBAL_CLAUDE_MD_ADDITIONS.md      — Claude context protocol
    schema/
      001_initial_schema.sql           — Supabase schema (3 tables + RLS)
    scheduled-tasks/
      brain_sync/                      — Every 4h: scan repos, detect contradictions
        SKILL.md + tools/
      morning_brief/                   — 6AM SGT daily Telegram briefing
      memory_sync/                     — Midnight: detect identity-level changes
      session_compress/                — 2AM: context entropy check
```

## Reading Order

1. `north-star/NORTH_STAR_SCHOLAR_BRAIN.md` — Vision and philosophy behind Al-Bayan
2. `north-star/PHASE_1_IMPLEMENTATION.md` — Technical spec for the 10-ayat proof of concept
3. `wingmen/WINGMEN_NERVOUS_SYSTEM_SPEC_v2.md` — Full system architecture for operational orchestration
4. Tool specs under `wingmen/scheduled-tasks/` — Individual scheduled task definitions

## Current Status

**Phase 1 has not yet started.**

Next action: ingest the first 10 ayat with dual tafsir (Ibn Kathir and Al-Sa'di) into Supabase, establishing the foundational data layer for the NORTH STAR reasoning engine.

## Deferred Items (Phase 2+)

- Multi-language i18n support
- Hadith integration and cross-referencing
- Madhab conflict resolution framework
- Scholar authentication and verification system
- Rate limiting
- Production monitoring and observability

---

Created by Musa (Gazzabyte).

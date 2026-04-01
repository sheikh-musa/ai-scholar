# WINGMEN NERVOUS SYSTEM — Full Build Spec v2

> **Purpose**: Pivot the existing Wingmen Orchestrator into a persistent nervous system that keeps both Claude Code (tactical, via Telegram) and claude.ai (strategic) fully aware of all Gazzabyte operations — with zero manual sync from Musa.
>
> **Owner**: Musa / Gazzabyte
> **Date**: 31 March 2026
> **Status**: READY TO BUILD
> **Version**: 2 — incorporates KAIROS consolidation, skeptical memory, context entropy management, coordinator parallelism, discrete tool architecture, commit attribution policy, and feature-flag rollout.

---

## Configuration

Machine-specific values that must be set before deployment:

| Variable | Description | Default | Where Used |
|----------|-------------|---------|------------|
| `GAZZABYTE_HOME` | Home directory for the Gazzabyte user | `/Users/musa` | scan_repo tool, LaunchAgent plist |
| `SUPABASE_URL` | Supabase project URL | — | All Supabase queries |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key | — | write_snapshot, brain_sync |
| `SUPABASE_ANON_KEY` | Supabase anonymous key | — | Read-only queries |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token for CTO channel | — | morning_brief, session_compress, alerts |
| `TELEGRAM_CHAT_ID` | Telegram chat/channel ID for alerts | — | All scheduled tasks |
| `TZ` | Timezone for scheduled tasks | `Asia/Singapore` | morning_brief (6AM), session_compress (2AM), memory_sync (midnight) |
| `BRAIN_MD_PATH` | Output path for BRAIN.md | `~/gazzabyte/BRAIN.md` | write_brain_md tool |
| `CHECKPOINT_PATH` | Output path for SESSION_CHECKPOINT.md | `~/gazzabyte/SESSION_CHECKPOINT.md` | session_compress |

---

## QUICK REFERENCE — What Gets Built

| Artifact | Location | Purpose |
|---|---|---|
| `schema.sql` | Deploy to Supabase | All new tables + indexes + RLS |
| `brain_sync/SKILL.md` | `~/.claude/scheduled-tasks/brain_sync/` | Orchestrator — runs every 4h |
| `brain_sync/tools/scan_repo.md` | `~/.claude/scheduled-tasks/brain_sync/tools/` | Scans a single repo |
| `brain_sync/tools/consolidate.md` | `~/.claude/scheduled-tasks/brain_sync/tools/` | Contradiction detection + confidence scoring |
| `brain_sync/tools/query_job_state.md` | `~/.claude/scheduled-tasks/brain_sync/tools/` | Reads jobs + build_runs |
| `brain_sync/tools/write_snapshot.md` | `~/.claude/scheduled-tasks/brain_sync/tools/` | Writes to Supabase + prunes |
| `brain_sync/tools/write_brain_md.md` | `~/.claude/scheduled-tasks/brain_sync/tools/` | Generates `~/gazzabyte/BRAIN.md` |
| `morning_brief/SKILL.md` | `~/.claude/scheduled-tasks/morning_brief/` | Daily 6AM Telegram brief |
| `memory_sync/SKILL.md` | `~/.claude/scheduled-tasks/memory_sync/` | Midnight diff + memory change detection |
| `session_compress/SKILL.md` | `~/.claude/scheduled-tasks/session_compress/` | 2AM context entropy check |
| `GLOBAL_CLAUDE_MD_ADDITIONS.md` | Append to `~/gazzabyte/CLAUDE.md` | Nervous system protocol |
| `LAUNCHAGENTS.md` | Reference — create .plist files manually | Mac Mini persistence |

---

## 1. ARCHITECTURE OVERVIEW

```
┌─────────────────────────────────────────────────────────────────────┐
│                        MAC MINI (Always On)                         │
│                                                                     │
│  ┌──────────────────────────┐    ┌─────────────────────────────┐   │
│  │     Claude Code CLI      │    │   Scheduled Tasks (4 total) │   │
│  │  --channels telegram     │    │                             │   │
│  │  ~/gazzabyte/            │    │  brain_sync      (every 4h) │   │
│  │                          │    │  morning_brief   (6AM SGT)  │   │
│  │  CLAUDE.md (global)      │    │  memory_sync     (midnight) │   │
│  │  BRAIN.md  (auto-gen)    │    │  session_compress (2AM SGT) │   │
│  │  All repos               │    │                             │   │
│  └──────────┬───────────────┘    └──────────────┬──────────────┘   │
│             │                                   │                  │
└─────────────┼───────────────────────────────────┼──────────────────┘
              │                                   │
              ▼                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      SUPABASE (Shared Brain)                         │
│                                                                      │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐   │
│  │  wingmen_brain   │  │ wingmen_brain_    │  │ brain_sync_log   │   │
│  │  (snapshots,     │  │ config           │  │ (audit trail of  │   │
│  │   append-only)   │  │ (repo registry,  │  │  every sync run) │   │
│  │                  │  │  feature flags)  │  │                  │   │
│  └────────┬─────────┘  └──────────────────┘  └──────────────────┘   │
│           │                                                          │
│  ┌────────┴──────────────────────────────────────────────────────┐   │
│  │           Existing Tables (unchanged)                         │   │
│  │   jobs   |   build_runs   |   repo_memory                    │   │
│  └───────────────────────────────────────────────────────────────┘   │
└──────────┬───────────────────────────────────────────────────────────┘
           │
    ┌──────┴──────┐
    │             │
    ▼             ▼
┌─────────┐  ┌──────────────┐
│Telegram │  │  claude.ai   │
│(Musa)   │  │  (Strategy)  │
│         │  │              │
│Tactical │  │  Supabase    │
│Execute  │  │  MCP reads   │
│Build    │  │  wingmen_    │
│Deploy   │  │  brain       │
│Fix      │  │              │
│Status   │  │  Verifies    │
│         │  │  freshness   │
│         │  │  before      │
│         │  │  asserting   │
└─────────┘  └──────────────┘
```

### Role Split

| Interface | Role | Access Method | Use For |
|---|---|---|---|
| Telegram → Claude Code | Tactical CTO | Channels plugin (persistent session) | Build, deploy, fix, ship, check status |
| claude.ai | Strategic CTO | Supabase MCP (queries `wingmen_brain`) | Planning, architecture, analysis, pivots |
| Claude Mobile / Dispatch | On-the-go | Remote Control / Dispatch | Quick checks, approve PRs, delegate |

---

## 2. SUPABASE SCHEMA

> **Deploy file**: `schema/schema.sql`
> **Order matters**: Run in the order tables appear — `wingmen_brain_config` before `wingmen_brain`.

### 2.1 `wingmen_brain_config` — Repo Registry with Feature Flags

```sql
CREATE TABLE IF NOT EXISTS wingmen_brain_config (
  repo_key          TEXT PRIMARY KEY,
  repo_path         TEXT NOT NULL,
  display_name      TEXT NOT NULL,
  vercel_project_id TEXT,
  status_category   TEXT NOT NULL
    CHECK (status_category IN ('active', 'done', 'paused', 'backlog')),
  track_revenue     BOOLEAN NOT NULL DEFAULT false,
  is_open_source    BOOLEAN NOT NULL DEFAULT false,   -- triggers commit attribution policy
  brain_sync_enabled BOOLEAN NOT NULL DEFAULT false,  -- FEATURE FLAG: roll out one repo at a time
  notes             TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed with current portfolio
-- brain_sync_enabled starts false for all. Enable selectively during rollout.
INSERT INTO wingmen_brain_config
  (repo_key, repo_path, display_name, vercel_project_id, status_category, track_revenue, is_open_source, brain_sync_enabled, notes)
VALUES
  ('wingmen',       '~/gazzabyte/wingmen',        'Wingmen Orchestrator', NULL,                            'active',  false, false, true,  'Enable first — used to validate brain_sync itself'),
  ('ihsandms',      '~/gazzabyte/ihsandms',        'IhsanDMS',            'prj_hDx9LayBrCSigSdcECYJFsejjaEO', 'active', true, false, true,  'Mosque/madrasah donation management. Active sales. Enable second.'),
  ('candy_motors',  '~/gazzabyte/candy-motors',    'Candy Motors',        NULL,                            'active',  true,  false, false, 'WhatsApp chatbot. PAYING CLIENT. Enable after first two validated.'),
  ('hifz_companion','~/gazzabyte/hifz-companion',  'Hifz Companion',      NULL,                            'active',  false, true,  false, 'Quran memorization PWA. Open-source waqf. Phase 1 complete.'),
  ('dookana',       '~/gazzabyte/dookana',         'Dookana',             NULL,                            'done',    false, false, false, 'Telegram-first micro-merchant. SHIPPED.'),
  ('al_mizan',      '~/gazzabyte/al-mizan',        'Al-Mīzān',            NULL,                            'backlog', false, false, false, 'Islamic knowledge ontology. Foundation layer.'),
  ('tadabbur',      '~/gazzabyte/tadabbur',        'Tadabbur',            NULL,                            'backlog', false, true,  false, 'Visual/interactive Quran. Open-source waqf.'),
  ('deenseeker',    '~/gazzabyte/deenseeker',      'DeenSeeker',          NULL,                            'paused',  false, false, false, 'Muslim Q&A with scholar verification.')
ON CONFLICT (repo_key) DO UPDATE SET
  repo_path          = EXCLUDED.repo_path,
  display_name       = EXCLUDED.display_name,
  vercel_project_id  = EXCLUDED.vercel_project_id,
  status_category    = EXCLUDED.status_category,
  track_revenue      = EXCLUDED.track_revenue,
  is_open_source     = EXCLUDED.is_open_source,
  notes              = EXCLUDED.notes,
  updated_at         = now();
-- Note: brain_sync_enabled is NOT updated on conflict — preserve manual rollout state.
```

### 2.2 `wingmen_brain` — Operational Snapshots (Append-Only)

```sql
CREATE TABLE IF NOT EXISTS wingmen_brain (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  snapshot_type         TEXT NOT NULL CHECK (snapshot_type IN ('full', 'delta')),
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  brain_sync_version    INTEGER NOT NULL DEFAULT 2,

  -- Computed freshness (in minutes since this snapshot was created)
  -- Used by claude.ai to decide how much to trust the data
  -- Queried as: EXTRACT(EPOCH FROM (now() - created_at)) / 60
  -- (Not stored as a generated column for Supabase compatibility — compute at query time)

  -- Overall sync health
  sync_health           TEXT NOT NULL DEFAULT 'ok'
    CHECK (sync_health IN ('ok', 'degraded', 'stale')),
  sync_health_reason    TEXT,          -- populated when sync_health != 'ok'

  -- Product-level operational state
  -- See Section 2.3 for full JSONB structure documentation
  products              JSONB NOT NULL DEFAULT '{}'::jsonb,

  -- Cross-cutting activity (last 24h across all repos)
  recent_activity       JSONB NOT NULL DEFAULT '[]'::jsonb,

  -- Aggregated signals for claude.ai
  active_blockers       TEXT[] NOT NULL DEFAULT '{}',
  revenue_pipeline      JSONB NOT NULL DEFAULT '{}'::jsonb,

  -- Wingmen orchestrator state
  wingmen_state         JSONB NOT NULL DEFAULT '{}'::jsonb,

  -- Free-form synthesis from the consolidation pass
  -- Includes contradiction notes, confidence reasoning, things Musa should know
  context_notes         TEXT DEFAULT NULL,

  -- Repos that were scanned in this run (subset of config where brain_sync_enabled = true)
  repos_scanned         TEXT[] NOT NULL DEFAULT '{}',

  -- Repos that failed to scan (timed out, missing, etc.)
  repos_failed          TEXT[] NOT NULL DEFAULT '{}'
);

-- Fast "latest snapshot" query
CREATE INDEX IF NOT EXISTS idx_wingmen_brain_created_at
  ON wingmen_brain (created_at DESC);

-- RLS
ALTER TABLE wingmen_brain ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access"
  ON wingmen_brain FOR ALL
  USING (auth.role() = 'service_role');

CREATE POLICY "Authenticated read"
  ON wingmen_brain FOR SELECT
  USING (auth.role() = 'authenticated');
```

### 2.3 `products` JSONB Structure — Full Contract

Every product entry in the `products` JSONB column must conform to this structure. Claude Code must validate against this before writing.

```jsonc
{
  "ihsandms": {
    // Identity
    "repo_key": "ihsandms",
    "display_name": "IhsanDMS",
    "status_category": "active",          // from wingmen_brain_config
    "deploy_url": "https://ihsandms.vercel.app",

    // Git state
    "last_commit_msg": "fix: PayNow QR dynamic generation",
    "last_commit_sha": "a1b2c3d",
    "last_commit_at": "2026-03-30T14:22:00Z",
    "commits_last_24h": 3,
    "commits_last_7d": 12,

    // Operational state (from STATUS.md)
    "current_phase": "Active sales",
    "status_raw": "deployed",             // building|testing|deployed|blocked|done
    "active_blockers": [
      "UEN for dynamic QR — awaiting Syukor"
    ],
    "next_milestones": [
      "Dynamic QR with UEN",
      "Multi-mosque support"
    ],
    "revenue_signals": [
      "Syukor requesting UEN — buying signal"
    ],

    // Confidence (set by consolidation pass)
    "health": "green",                    // green|yellow|red|archived
    "confidence": "high",                 // high|medium|low
    "confidence_reason": "STATUS.md and git log agree — active commits, deployed status confirmed",

    // Contradiction flags (set by consolidation pass — empty if none)
    "contradictions": [],

    // Scan metadata
    "status_md_found": true,
    "status_md_last_updated": "2026-03-30T14:25:00Z",
    "scan_succeeded": true,
    "scan_error": null
  }
}
```

### 2.4 `brain_sync_log` — Audit Trail

```sql
CREATE TABLE IF NOT EXISTS brain_sync_log (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  trigger       TEXT NOT NULL CHECK (trigger IN ('scheduled', 'manual', 'on_demand')),
  duration_ms   INTEGER,
  snapshot_id   UUID REFERENCES wingmen_brain(id),
  repos_scanned INTEGER NOT NULL DEFAULT 0,
  repos_failed  INTEGER NOT NULL DEFAULT 0,
  contradictions_found INTEGER NOT NULL DEFAULT 0,
  sync_health   TEXT NOT NULL,
  error_detail  TEXT           -- populated if the entire run failed
);

ALTER TABLE brain_sync_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access"
  ON brain_sync_log FOR ALL
  USING (auth.role() = 'service_role');

CREATE POLICY "Authenticated read"
  ON brain_sync_log FOR SELECT
  USING (auth.role() = 'authenticated');
```

---

## 3. SCHEDULED TASKS — Overview

All tasks live in `~/.claude/scheduled-tasks/`. Each task is a folder with a `SKILL.md` orchestrator and (where applicable) a `tools/` subfolder of discrete sub-agent tools.

| Task | Schedule | Approx Duration | Depends On |
|---|---|---|---|
| `brain_sync` | Every 4h | 2–5 min | Supabase connection, repos exist |
| `morning_brief` | 6:00 AM SGT daily | 30s | Latest `wingmen_brain` row |
| `session_compress` | 2:00 AM SGT daily | 1 min | Telegram session running |
| `memory_sync` | Midnight SGT daily | 1 min | Latest 2 `wingmen_brain` rows |

**Schedule commands** (run inside Claude Code CLI):

```bash
/schedule create brain_sync --every "4 hours"
/schedule create morning_brief --daily "06:00" --timezone "Asia/Singapore"
/schedule create session_compress --daily "02:00" --timezone "Asia/Singapore"
/schedule create memory_sync --daily "00:00" --timezone "Asia/Singapore"
```

---

## 4. STATUS.md PROTOCOL (MANDATORY)

Every repo under `~/gazzabyte/` that is registered in `wingmen_brain_config` MUST have a `STATUS.md` at its root. This is what `brain_sync` reads.

**Format** (Claude Code must write this format exactly — the scanner parses specific field names):

```markdown
# STATUS — [Product Display Name]

Last Updated: 2026-03-30T14:25:00Z
Phase: [current phase description]
Status: deployed
Deploy URL: https://ihsandms.vercel.app
Health: green

## Completed
- PayNow QR generation with dynamic merchant name
- Multi-step donation flow
- Zakat calculator

## Blocked
- Dynamic QR with UEN — awaiting Syukor to provide UEN number

## Next Up
- Multi-mosque support
- Recurring donation scheduling

## Revenue Signals
- Syukor requesting UEN — strong buying signal

## Questions for CTO (claude.ai)
- Should we prioritise multi-mosque support before closing IhsanDMS deal?
```

**Valid Status values**: `building` | `testing` | `deployed` | `blocked` | `done`
**Valid Health values**: `green` | `yellow` | `red`

---

## 5. CLAUDE.AI INTEGRATION

### 5.1 How claude.ai reads the brain

claude.ai has Supabase connected as an MCP connector. When Musa opens a strategic conversation, claude.ai should:

```sql
-- Step 1: Get the latest snapshot
SELECT
  id,
  created_at,
  sync_health,
  sync_health_reason,
  EXTRACT(EPOCH FROM (now() - created_at)) / 60 AS freshness_minutes,
  products,
  recent_activity,
  active_blockers,
  revenue_pipeline,
  wingmen_state,
  context_notes,
  repos_scanned,
  repos_failed
FROM wingmen_brain
ORDER BY created_at DESC
LIMIT 1;
```

### 5.2 Freshness-aware behavior (CRITICAL)

claude.ai MUST check `freshness_minutes` before making operational claims:

| Freshness | Behavior |
|---|---|
| < 60 min | Trust fully. Assert normally. |
| 60–300 min | Trust with timestamp. Say "as of [time]" for operational claims. |
| > 300 min | Flag staleness to Musa. Treat all operational data as hints only. |
| sync_health = 'degraded' | Surface `sync_health_reason`. Ask Musa to confirm key facts. |
| Any product `confidence: low` | Surface the contradiction before making decisions about that product. |

### 5.3 Memory edits — what goes where

**In claude.ai memory edits** (slow-changing identity context):
- Vision path and north star
- Product portfolio overview (names + purpose — not status)
- Interaction preferences and hard constraints
- Life context (location, day job, etc.)

**In `wingmen_brain` via Supabase** (fast-changing operational context):
- Deploy URLs and last commit info
- Blockers and milestones
- Revenue signals and pipeline
- Wingmen queue state

Never duplicate operational state into memory edits — it goes stale and creates contradictions.

---

## 6. TELEGRAM CHANNEL SETUP

### 6.1 Prerequisites

```bash
# Install Bun (required for official Telegram plugin)
curl -fsSL https://bun.sh/install | bash

# Verify
bun --version
```

### 6.2 Bot Setup

1. Open @BotFather on Telegram
2. `/newbot`
3. Name: `Wingmen CTO`
4. Username: `wingmen_cto_bot` (pick whatever is available)
5. Copy the bot token — you'll need it in step 6.3

### 6.3 Configure and Launch

```bash
# Inside a Claude Code session:
/plugin install telegram@claude-plugins-official
/telegram:set-token YOUR_BOT_TOKEN_HERE

# Launch persistent session (run from Mac Mini terminal — this is the always-on command)
cd ~/gazzabyte
claude --channels plugin:telegram@claude-plugins-official --dangerously-skip-permissions
```

### 6.4 LaunchAgent — Persistent Session

Create `~/Library/LaunchAgents/com.gazzabyte.wingmen-cto.plist`:

> **Note**: All `/Users/musa/` paths in this plist must be updated to match your `GAZZABYTE_HOME` value (see Configuration section).

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.gazzabyte.wingmen-cto</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/claude</string>
    <string>--channels</string>
    <string>plugin:telegram@claude-plugins-official</string>
    <string>--dangerously-skip-permissions</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/musa/gazzabyte</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/Users/musa/gazzabyte/logs/wingmen-cto.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/musa/gazzabyte/logs/wingmen-cto-error.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key>
    <string>/Users/musa</string>
    <key>PATH</key>
    <string>/usr/local/bin:/usr/bin:/bin:/Users/musa/.bun/bin</string>
    <key>WINGMEN_SESSION_START</key>
    <string>__SET_AT_LAUNCH__</string>
  </dict>
</dict>
</plist>
```

```bash
# Load:
mkdir -p ~/gazzabyte/logs
launchctl load ~/Library/LaunchAgents/com.gazzabyte.wingmen-cto.plist

# Verify it's running:
launchctl list | grep gazzabyte
```

---

## 7. MIGRATION FROM EXISTING ORCHESTRATOR

### 7.1 What stays

- `jobs` table — unchanged
- `build_runs` table — unchanged
- `repo_memory` table — unchanged
- `gazzabyte_orch.py` worker — keep running
- Existing LaunchAgents for the orchestrator worker — keep

### 7.2 What gets added

- `wingmen_brain` table
- `wingmen_brain_config` table (replaces REPOS.json for brain purposes)
- Four scheduled tasks
- Updated `~/gazzabyte/CLAUDE.md`

### 7.3 What gets retired (only after validation)

| Old Component | Replacement | Retire When |
|---|---|---|
| Custom `cto_bot.py` | Official Telegram channel plugin | Telegram channel stable for 48h |
| Manual STATUS.md checking | `brain_sync` automated scan | brain_sync validated on 2+ repos |
| Manual claude.ai/Claude Code sync | `wingmen_brain` via Supabase MCP | claude.ai confirmed reading brain |

### 7.4 Migration order (STRICT — do not skip steps)

```
1.  Deploy schema.sql to Supabase (wingmen_brain_config + wingmen_brain + brain_sync_log)
2.  Verify tables created: SELECT * FROM wingmen_brain_config;
3.  Create STATUS.md stubs in wingmen and ihsandms repos (just these two first)
4.  Update ~/gazzabyte/CLAUDE.md with nervous system additions
5.  Copy scheduled task files to ~/.claude/scheduled-tasks/
6.  Run brain_sync MANUALLY for wingmen repo only: /task run brain_sync
7.  Verify: SELECT * FROM wingmen_brain ORDER BY created_at DESC LIMIT 1;
8.  Check ~/gazzabyte/BRAIN.md was generated and readable
9.  Enable ihsandms in brain_sync_config: UPDATE wingmen_brain_config SET brain_sync_enabled = true WHERE repo_key = 'ihsandms';
10. Run brain_sync again manually — verify both repos appear in snapshot
11. Set up Telegram channel plugin and verify /status command works
12. Schedule all four tasks
13. Wait for 6AM morning_brief — verify Telegram message received
14. Open claude.ai → query wingmen_brain via Supabase MCP → verify freshness and data
15. Enable remaining repos in brain_sync_config one at a time
16. Retire cto_bot.py only after Telegram channel has been stable for 48h
```

---

## 8. VALIDATION CHECKLIST

### Schema
- [ ] `wingmen_brain_config` created and seeded (8 repos)
- [ ] `wingmen_brain` created with correct columns and RLS
- [ ] `brain_sync_log` created with RLS
- [ ] `SELECT * FROM wingmen_brain_config;` returns 8 rows
- [ ] `SELECT brain_sync_enabled FROM wingmen_brain_config;` — only wingmen and ihsandms are true

### brain_sync (Manual Run First)
- [ ] Runs without error on wingmen repo
- [ ] Snapshot written to `wingmen_brain` — `SELECT id, created_at, repos_scanned FROM wingmen_brain LIMIT 1;`
- [ ] `~/gazzabyte/BRAIN.md` generated and readable
- [ ] `brain_sync_log` has an entry for the run
- [ ] Contradiction detection: manually introduce a STATUS.md mismatch, run again, verify confidence drops to "medium" or "low"

### Scheduled Tasks
- [ ] All four tasks registered: `/schedule list`
- [ ] `morning_brief` sends Telegram message at 6AM (verify day after setup)
- [ ] `session_compress` runs at 2AM without crashing (check logs)
- [ ] `memory_sync` generates `MEMORY_SYNC_LOG.md` (or does nothing if no changes)

### claude.ai Integration
- [ ] Supabase MCP connected in claude.ai
- [ ] Manual SQL query in claude.ai returns latest `wingmen_brain` row
- [ ] Freshness field computed correctly: `EXTRACT(EPOCH FROM (now() - created_at)) / 60`
- [ ] claude.ai correctly flags stale data when snapshot is > 5h old (test by checking timestamp)

### Telegram
- [ ] LaunchAgent loaded and running
- [ ] Claude Code responds to messages via Telegram
- [ ] After Mac Mini reboot, session restarts automatically

---

## 9. HARD CONSTRAINTS

These apply to ALL code written for the nervous system (from GLOBAL_CLAUDE.md):

- **Async Python only** — no blocking calls in any Python scripts
- **No bare dicts** — use Pydantic models or dataclasses
- **RLS on all Supabase tables** — no exceptions
- **Append-only writes** to `wingmen_brain` — never UPDATE or DELETE a snapshot (only prune old ones via scheduled cleanup)
- **Audit log every write** — `brain_sync_log` entry for every brain_sync run, success or failure
- **Graceful degradation** — if brain_sync fails, Telegram session and morning_brief still work (they use stale data and say so)
- **Quranic principles are hard constraints** — no riba, zakat transparency by default in any revenue-adjacent feature

---

## 10. SUCCESS CRITERIA

The nervous system is working when all six of these are true:

1. Musa opens claude.ai and gets "I see IhsanDMS had a deploy yesterday and Syukor's UEN request is still the top blocker" — without pasting anything
2. Musa's Telegram shows a brief at 6AM with accurate state across all active products
3. Musa can message the Telegram bot to build/deploy without opening a terminal
4. No manual sync is required between any Claude instance
5. Claude Code updates STATUS.md automatically as part of every build/deploy workflow
6. If brain_sync fails three times in a row, Musa gets a Telegram alert — all other functions degrade gracefully with stale data rather than crashing

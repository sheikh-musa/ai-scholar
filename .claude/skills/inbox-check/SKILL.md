---
name: inbox-check
description: Invoke this skill BEFORE responding to any inbox-status query from Musa ("ping", "pong?", "inbox", "anything new", "what's pending", "new messages", "any responses", or any semantic variant). Executes a fresh SELECT against agent_messages for the current CC identity — does not report from session context. Stale reports are a governance integrity violation per ORCHESTRATOR-NOTIFIER-FIX-001-AMEND Fix 4.
---

# Inbox-Check

Cross-cutting governance skill for every CC agent (cc-ihsanos, cc-scholar, cc-cosem, future). Addresses the acute bug ORCHESTRATOR-NOTIFIER-FIX-001-AMEND diagnosed: CC agents reporting "inbox clean" from session context while the database has unread messages queued. Musa caught this once; it should not happen again.

## Hard Invariants

**I-1 — Fresh SELECT before every inbox-status response.**
When the user issues any inbox-status query (pong, ping, pending, any synonym), the CC must execute a live query against `agent_messages` before composing the response. Session-context reports are prohibited and are recorded as a governance integrity violation.

**I-2 — `read_at` populated on every processed message.**
When a CC agent processes an inbox row (whether to respond, defer, triage, or ignore), it must `UPDATE agent_messages SET read_at = now() WHERE id = ?`. Not optional. Feeds the `unread_backlog` observability surface in boot_briefing (per AMEND Fix 5).

**I-3 — Boot-time inbox query.**
At session start, the CC runs the inbox query as part of boot protocol and surfaces the pending count in its opening response. Prevents "just booted, don't know what's pending" blind spot. For Claude Code agents, this is enforced via a session-start memory directive or hook per the agent's native runtime.

**I-4 — Query scope.**
The three queries run on every inbox-status response:

```sql
-- (a) Unread inbox
SELECT id, from_agent, message_type, subject, priority, created_at
  FROM agent_messages
 WHERE to_agent = '<my_agent_id>' AND read_at IS NULL
 ORDER BY created_at DESC;

-- (b) My open challenges/questions awaiting response
SELECT id, subject, created_at
  FROM agent_messages
 WHERE from_agent = '<my_agent_id>'
   AND requires_response = true
   AND responded_at IS NULL
 ORDER BY created_at DESC;

-- (c) New challenge_window decisions touching my scope (since last boot or last check)
SELECT decision_ref, title, challengeable_until, repos_affected
  FROM strategic_decisions
 WHERE challenge_status = 'challenge_window'
   AND created_at >= <last_check_timestamp>
 ORDER BY created_at DESC;
-- Filter client-side to those where my repo scope is in repos_affected.
```

**I-5 — No stale-cache responses.**
Even if the CC queried < 60 seconds ago, a new inbox-status query from the user triggers a fresh query. The cost of a stale response (governance integrity violation) vastly exceeds the cost of a duplicate query (sub-second round-trip).

## How to identify the current agent id

Each CC session knows its identity from the session's system prompt or CLAUDE.md inheritance. Canonical mapping:

| Repo cwd | Agent id |
|---|---|
| `~/wingmen/projects/ai-scholar/` | `cc-scholar` |
| `~/wingmen/projects/hifz-companion/` | `cc-hifz` (when/if spawned) or `cc-scholar` (currently handles scholar+hifz as a single family) |
| `~/wingmen/projects/ihsanos/` | `cc-ihsanos` |
| `~/wingmen/projects/cosem-tdu/` | `cc-cosem` |
| `~/wingmen/projects/wingmen-orchestrator/` | `cc-orchestrator` |

If ambiguous (e.g., session opened from a parent directory), read the current working directory via the shell and pick the most specific child that matches.

## How to apply the check result

After running the three queries, compose the response as follows:

- **Report-only responses (`ping`, `pong?`):** one-line summary.
  - `no new CAI traffic since <last-check-time>` (if all three queries returned empty).
  - `unread: <n> inbox + <m> open challenges + <k> new decisions` (if any non-empty).
- **Action-flagging responses** when any of:
  - A `response_ref` has appeared on a prior challenge I filed → surface it prominently.
  - A challenge-window decision expires within 24h and is not yet reviewed against Ihsan criteria → flag for review.
  - An unread message has `priority='P0'` or `'P1'` → surface immediately.

If any of the above triggers, the response includes a concrete next-action proposal, not just status.

## Mark-as-read discipline (I-2)

When the CC decides how to handle an inbox message:

| Decision | Mark read? |
|---|---|
| Respond (any message_type) | YES — `read_at = now()` on the message you just responded to |
| Defer (plan to respond later) | YES — `read_at = now()`; note deferral in a local TODO/task |
| Triage only (no response needed: FYI, digest, notification) | YES — `read_at = now()` |
| Ignore (spam, irrelevant) | YES — `read_at = now()`; add `skipped_at = now()` if the schema supports it |

The ONLY state where `read_at` stays NULL is "agent has not yet processed this message." Once processed, `read_at` is written immediately.

## Validation

`scripts/validate_inbox_check.sh` (infrastructure, cc-ihsanos):

- Lints CC session logs for responses to inbox-status queries that were not preceded by a SELECT query on `agent_messages` within the past 5 minutes (proposed `cc_inbox_queries` telemetry table per AMEND AC-16).
- Reports agents whose `unread_backlog` count exceeds a threshold in boot_briefing (per AMEND AC-17).

## Failure modes this skill prevents

1. **Stale-context report:** CC says "inbox clean" because it was clean at session start, but messages arrived in the meantime. Fresh query catches this.
2. **Unprocessed-but-delivered:** Telegram notifier delivered (`forwarded_to_telegram_at` populated) but CC never processed. `read_at` discipline surfaces the gap.
3. **Missed challenge windows:** A new challenge-window decision lands and closes before any CC reviews it. I-4(c) + prominent-flag rule surfaces it.
4. **Inbox-bankruptcy regress:** CC pretends inbox is clean by never querying. Telemetry side (I-5, cc_inbox_queries) catches the non-query.

## Not enforced here (out of scope)

- **Cross-agent inbox coordination.** When one CC needs another CC's attention, it files a message with `to_agent` set appropriately; this skill only covers the receiving side.
- **Challenge authoring.** Separate governance surface — see each CC's CLAUDE.md for the challenge protocol.
- **Boot_briefing format.** Owned by wingmen-orchestrator; this skill just mandates the boot-time query.

## References

- ORCHESTRATOR-NOTIFIER-FIX-001-AMEND — Fix 4 (CC inbox-check protocol) + Fix 5 (read_at discipline audit)
- CAI-RESP-073 — skill priority order (this skill proposed at slot #7.5)
- PIPELINE_CONSTRAINTS §8 (Communication Latency) — ihsanos CLAUDE.md reference; superseded for CCs that have this skill autoloaded

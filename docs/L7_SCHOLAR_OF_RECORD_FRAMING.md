# L7 Scholar-of-Record Framing — Question to CAI

**Status:** Draft for Musa eyeball → CAI as `agent_messages` question.
**Author:** cc-scholar.
**Decision class:** Ihsan-level (governance / VISION-003 INV-7). Per `feedback_cc_challenges_cai.md`, cc-scholar drafts the framing but does NOT author the ruling.
**Blocks:**
- INV-8 audit-substrate scholar ruling (per `docs/INV-8-scholar-question.md`: "scholar-of-record pairing protocol is not yet defined")
- AL-BAYAN-001 ruling-class queries (currently emit 4-tier-transparency refusal in lieu of pairing)
- Any user-facing ruling emission (gated by F-3 scholar-gate routing)

## Why this question now

The Wingmen stack has two ruling-shaped surfaces — Al-Bayān (live retrieval) and INV-8 (audit substrate) — and both currently route ruling-class queries through a refusal because pairing isn't operationalised. The question is well-defined enough to file:

> What is the minimum-viable scholar-of-record pairing protocol that lets us emit ruling-class output through F-3 routing, while honoring INV-7 (no AI-emitted rulings without scholar in the loop)?

Not asking *whether* to pair — that's settled by INV-7. Asking *how* to operationalize pairing with an actual scholar at v0.1 scale.

## The three open dimensions (and proposals)

### Dimension 1 — Scholar count: single vs panel

| Option | Pro | Con |
|---|---|---|
| **Single scholar (proposed)** | Lowest coordination cost, fast cycle time, single accountable signature, lowest cost-per-query | Single point of failure if scholar unavailable; no built-in tarjih (weighing of opinions) |
| Panel of 3 | Built-in disagreement surface, more authoritative output | Pre-launch we don't have 3 scholars; 3× cost; coordination delay |
| Panel of N (variable) | Maximum legitimacy | Operationally unrealistic at v0.1 |

**Proposal: single scholar to start.** Reasons: (a) we don't yet have an N≥3 scholar bench; (b) the F-3 refusal posture means single-scholar outage degrades to "no ruling emitted" — failure mode is conservative, not wrong; (c) Al-Bayān's v0.1 monthly query volume is small enough that one scholar at part-time hours is sufficient.

**Path to panel:** revisit when (a) we have ≥3 candidate scholars under retainer-or-equivalent, or (b) ruling-query volume exceeds single-scholar capacity, or (c) a category requires tarjih by design (e.g., contemporary fiqh-of-the-internet rulings where multiple madhab views need surfacing).

### Dimension 2 — Ruling-category scope: narrow start vs broad

| Option | Pro | Con |
|---|---|---|
| **Single category (proposed: financial-muamalat)** | Concrete subject-matter boundary; aligns with WAQFTOOL-01 + W-2 monetisation; lowest tafsir-defense ambiguity (most has codified Hanafi rulings); easiest scholar recruitment | Excludes ibadat / family / criminal categories from ruling-class emission at launch |
| Broad scope (all categories) | Maximum user value | Requires polymath scholar OR per-category panel; high ambiguity surface |
| Narrow start, expand by review | Same as single but with explicit ramp | Same as single + needs an expansion protocol |

**Proposal: financial-muamalat only at launch.** Reasons: (a) directly serves the waqf monetisation use case (W-2); (b) Hanafi muamalat fiqh has substantial codified base — lowest risk of model emitting AI-generated content that needs scholar correction; (c) recruitment pool is widest in this category; (d) failure cost is bounded — financial questions have less existential stakes than e.g. divorce or inheritance disputes.

**Out of scope at launch (route to F-3 refusal):** ibadat, family law, criminal, theological, contemporary social-issues. Add categories one at a time after the first 90-day review cycle confirms operational fit.

### Dimension 3 — Review cadence: weekly / fortnightly / per-query

| Option | Pro | Con |
|---|---|---|
| **Weekly (proposed: 60-min async batch + 30-min sync)** | Predictable scholar workload; batch efficiency; Friday cycle naturally aligns with khutbah / weekly Islamic rhythm | Up to 7-day lag on novel queries — for non-emergent rulings this is fine, but blocks any time-sensitive use case |
| Fortnightly | Lower scholar cost | Up to 14-day lag; queue backpressure if volume rises |
| Per-query (real-time) | Zero lag | Operationally unrealistic at v0.1 |
| Tiered (real-time for emergent + weekly batch for rest) | Best of both | Requires emergent classifier which we don't have |

**Proposal: weekly cadence.** 60-min async review covers the queued queries (scholar reviews proposed responses + supporting tafsir / hadith retrieval, signs off or amends); 30-min sync covers (a) escalated / ambiguous cases, (b) calibration drift discussions, (c) audit-trail review. Total: 90 min/week.

**Day:** propose Friday post-Asr (works for SG/ID timezone scholars). Open to scholar preference.

**Lag implication:** publish a "submitted; ruling pending review on Friday" interstitial for queries that arrive between cycles. Refusal-with-acknowledgment, not silent drop.

## Recruitment / engagement (also open)

The framing above assumes we have a scholar to engage. Open sub-questions for CAI / Musa:

- **Identity:** Named candidate (if Musa has one), or RFP / formal recruitment process?
- **Compensation model:** Stipend, per-query, retainer, waqf-funded? Affects the W-2 monetisation question and INV-2 (no-riba) capital stack constraint.
- **Madhab anchor:** Hanafi (matches WAQFTOOL-01 founder-mutawalli declaration), or madhab-explicit per ruling? Default: Hanafi at launch with explicit `madhab` field on every ruling row so future re-issue against another madhab is mechanically possible.
- **Geographic / institutional fit:** SG (MUIS-aligned), ID (MUI / NU / Muhammadiyah), or transnational? Affects regulatory legibility.

## What I'm asking CAI to rule on

A `strategic_decisions` row with the four committed answers:
1. Scholar count for v0.1 (proposal: single)
2. Category scope for v0.1 (proposal: financial-muamalat)
3. Review cadence for v0.1 (proposal: weekly 60+30)
4. Recruitment model (proposal: named-candidate-first if Musa has one in mind, else RFP-via-MUIS-or-equivalent at v0.2)

If CAI accepts the proposed defaults: cc-scholar drafts the operational protocol (queue table, review SOP, scholar dashboard scope) and files a follow-up implementation strategic_decisions row.

If CAI revises any dimension: we accept the revision and draft accordingly.

If CAI defers (e.g., "wait for more data"): we keep F-3 refusal posture indefinitely and document the deferral in INV-8-scholar-question.md as the resolution.

## What this draft does NOT do

- Doesn't name a specific scholar (Musa-direct call).
- Doesn't pre-commit a compensation model (entangled with W-2 — separate decision).
- Doesn't enable INV-8 Solana-anchoring path (still gated by INV-8-scholar-question.md ruling on PoS / underlying chain — that's a different scholar question).
- Doesn't replace the 4-tier-transparency refusal posture for non-financial-muamalat queries — those continue to refuse.

## References

- VISION-003 INV-7 — no AI-emitted rulings without scholar in the loop
- AL-BAYAN-001 — F-3 scholar-gate routing as authored
- `docs/INV-8-scholar-question.md` — the parent question this framing partially unblocks
- `docs/WAQFTOOL-01-hanafi-declaration.md` — Hanafi madhab anchor for monetisation context
- `docs/4-tier-transparency` skill — INV-6 action_prompt carve-out (financial-muamalat is a subset of `query_type='ruling'`)
- `feedback_cc_challenges_cai.md` — why this is filed as question, not authored as decision

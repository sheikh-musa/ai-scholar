# INV-8 Audit-Trail Substrate — Scholar-of-Record Question

**Status:** QUEUED for L7 cycle 2–3 review (per CAI-RESP-110, 2026-04-29). Was BLOCKED pending pairing; pairing landed.
**Parent:** VISION-003 INV-8, CAI-RESP-062 (scholar ruling gate), CAI-RESP-110 (L7 pairing + cycle sequencing)
**Owner:** cc-scholar (drafting); `<L7_SCHOLAR_OF_RECORD>` (ruling, post-cycle-1)
**Blocks:** Solana-anchoring path on Al-Bayān rulings; does NOT block Postgres-Merkle fallback (already shipping path)

## The question (for the scholar)

Al-Bayān commits under VISION-003 INV-8 to publish a tamper-evident audit trail of every ruling it emits — "every ruling is Merkle-pinned via IhsanOS Layer 1 trust infrastructure; retroactive revision impossible." The candidate substrate for this Merkle pin is the Solana blockchain (proof-of-stake).

Under VISION-003 INV-2, Al-Bayān's capital stack must be halal — no riba-yielding instruments, no riba treasury, no riba payment rails.

**The specific question we need ruled:**

Does Al-Bayān's use of the Solana blockchain as an audit-anchor substrate — where Al-Bayān pays a one-time transaction fee per ruling Merkle root (approx. 0.000005 SOL per write, no staking, no holding of SOL beyond the transactional amount needed to pay fees) — constitute participation in an impermissible financial arrangement under any of the following frames?

1. **Riba al-fadl** — the transaction fee flows to validators as a block reward, which is economically derived in part from their staked SOL. By paying fees, are we contributing to a pool that finances staking yield for others?

2. **Riba al-nasi'ah** — Solana's inflation issuance and epoch-based staking rewards resemble time-value yield on capital. Does our transaction touch that mechanism sufficiently to bind us?

3. **Tasharruf fi-l-haram / cooperation on sin (ta'awun 'ala-l-ithm wa-l-'udwan, Q 5:2)** — even if we do not stake SOL ourselves, does paying fees to a system whose validators earn staking rewards constitute cooperation in impermissible yield?

4. **Jahala / gharar** — the network fee price is deterministic per-transaction, but the validator rewards derived from it involve multi-party randomness. Does this rise to the level of haram gharar for the payer?

## Contexts where the ruling applies

This ruling determines Al-Bayān's architectural choice for INV-8 substrate across all ruling emissions. It does not extend to:
- Personal use of crypto by founders (separate personal muhasabah).
- Product-level payment acceptance (separate question covered by INV-2 payment-rails clause).
- Other blockchain use cases (e.g., identity) where the same cost-benefit may differ.

## Alternatives if the ruling is negative

Per CAI-RESP-062, the accepted fallback is:

> Append-only Postgres ledger with signed Merkle roots published to git — same audit property, no crypto substrate.

Technical design: see `docs/INV-8-postgres-merkle-fallback.md`. The fallback preserves the INV-8 audit invariant (retroactive revision impossible) at the cost of requiring git-host trust (GitHub/Codeberg/self-hosted) in place of blockchain public witness. A ruling against Solana would route Al-Bayān to this fallback; a positive ruling permits Solana; a qualified ruling (e.g., "permissible only if staking-reward-revenue share to validators is minimized") would point to specific alternative chains (e.g., a validator set that does not stake-reward, or a proof-of-authority substrate used by some Islamic-finance consortia).

## What we are asking the scholar to produce

A written ruling suitable for publication on Al-Bayān's transparency dashboard. Minimum content:

1. The ruling (`permitted` / `permitted-with-conditions` / `not-permitted`) and the specific frame(s) applied (1–4 above).
2. The dalil (Qur'an, Sunnah, classical fiqh references, contemporary ijtihad citations as applicable).
3. Any conditions under which the ruling changes (e.g., if Solana transitions to a different consensus).
4. The scholar's name, credentials, madhab, and consent to publication.

## Filing

Ruling will be filed to `strategic_decisions` as its own decision ref (`AL-BAYAN-INV8-RULING-001`) and cross-referenced from VISION-003 INV-8. Published on the Al-Bayān transparency dashboard alongside the waqf annual report (per VISION-003-WAQF-01 W-8).

## Process to pair a scholar

**Update 2026-04-29 (CAI-RESP-110):** L7 scholar-of-record pairing protocol has been ruled. Named candidate paired (Shāfi'ī, fi sabilillah, Part 6(iii) graceful-conversion clause active). PoS-halal routing to L7 is **confirmed but sequenced cycle 2–3**, not cycle 1. Cycle 1 is the WAQFTOOL-01 Hanafi → Shāfi'ī amendment (`docs/CAI-WAQFTOOL-AMEND-001-shafii-amendment.md`) — chosen for low blast radius before this question (highest-stakes ruling) is loaded onto the new pipeline.

This question therefore moves from BLOCKED → QUEUED. It enters the L7 review queue once cycle-1 (WAQFTOOL amendment) closes successfully and any L7-PROCESS-001 SOP gaps surfaced during cycle-1 are remediated. v0.1 audit substrate continues to ship via the Postgres-Merkle fallback (`docs/INV-8-postgres-merkle-fallback.md`); a positive ruling on Solana is a later migration; a negative ruling makes the fallback the permanent substrate.

Open item: F-3 refusal posture for ruling-class queries remains active until L7 onboarding doc is signed and cycle-1 completes (per CAI-RESP-110).

# Modal Privacy Verification — pre-execution checklist

**Status:** Scaffold authored 2026-04-28. Execution gates Phase A backfill kickoff per CAI-RESP-095 (A).
**Owner:** cc-scholar (verification execution); requires Modal account access.
**Trigger:** complete BEFORE EMBED_PIPELINE_v02 backfill kickoff.
**Escalation:** any check returns BLOCKER → file `ARCH-AL-BAYAN-MODAL-PRIVACY-001` and PAUSE.

## Why this exists

CAI-RESP-095 (A) accepted Modal-first hosting for v0.2 conditional on verifying that the Modal posture honors amanah on user query data. Managed compute (our container, our weights, our code) is qualitatively different from vendor inference API (their model, their text access) — but managed compute is not managed amanah until verified. Fatabayyanu (Q 49:6) applies to cloud substrate.

## The 5 mandatory checks

Each check has: question, expected default, verification method, blocker condition, mitigation if non-default.

### Check 1 — Query-payload logging

**Question:** Does Modal capture query payloads (request body / stdout / stderr) by default in any logging surface accessible to Modal operators or persistence beyond the request lifecycle?

**Expected default to verify:** request body NOT logged; stdout/stderr captured but does not contain query text unless our container code prints it.

**Verification method:**
- [ ] Read Modal docs section "Logs" — exact behavior.
- [ ] Test: deploy a stub container that echoes a fingerprint string on a known input. Send query; check Modal log dashboard for whether the fingerprint appears.
- [ ] Verify our container code does NOT print query text to stdout/stderr (defensive: structured-logging only with redacted fields).

**Blocker condition:** Modal default logs request bodies in a way we can't disable, OR operator can retrieve query text from logs at any time.

**Mitigation if non-default but disable-able:** set the logging-disable env config; document in `docs/model-cards/<encoder>.md`; verify by re-running the fingerprint test.

**Result:** TBD — pending Modal account access.

### Check 2 — Operator access boundary

**Question:** What can Modal operators access in normal operation vs break-glass scenarios? Specifically: container memory state, container filesystem, network traffic in/out, secrets/env vars.

**Expected default to verify:** operators cannot read container memory or filesystem in normal operation. Break-glass requires customer notification (or at least audit log) and is rare.

**Verification method:**
- [ ] Read Modal "Security" + "Privacy" + "Compliance" docs.
- [ ] Check Modal SOC 2 / ISO 27001 attestations for the relevant control objectives.
- [ ] Confirm whether "Modal staff support session" requires customer consent.
- [ ] Document the break-glass procedure (if exists) — what's the trigger, what's the audit trail, who can authorize.

**Blocker condition:** operators have routine access to container memory/filesystem, OR break-glass has no audit trail, OR no SOC 2 / equivalent attestation.

**Mitigation if non-default:** evaluate whether break-glass concerns are mitigatable (e.g., contract addendum, dedicated tenant). If not → blocker, file `ARCH-AL-BAYAN-MODAL-PRIVACY-001`, PAUSE.

**Result:** TBD.

### Check 3 — Container data residency

**Question:** Where does Modal schedule containers? Cross-region? Specifically: is there cross-border data flow from Singapore (primary user base) into US/EU jurisdictions with mandatory-disclosure regimes (e.g., FISA 702, GDPR data-access requests)?

**Expected default to verify:** containers can be region-pinned. Default region acceptable for our user base (Singapore + Indonesia).

**Verification method:**
- [ ] Check Modal "Regions" docs — list of available regions.
- [ ] Identify Modal's APAC region(s).
- [ ] Verify: can we pin to APAC region in container config?
- [ ] If default region is US/EU and APAC pinning available → pin to APAC.
- [ ] If only US/EU available → evaluate against MOJ/AGC Singapore data-residency expectations for waqf-products (consult before final decision).

**Blocker condition:** containers run only in jurisdictions with mandatory-disclosure regimes incompatible with Muslim user query confidentiality, AND no APAC alternative.

**Mitigation:** region-pin to APAC if available; document which region in `docs/model-cards/<encoder>.md` AND in EMBED_PIPELINE_v02 §hosting-privacy result section.

**Result:** TBD.

### Check 4 — Encryption-at-rest

**Question:** For any persisted state (logs, container images, secrets, snapshots), is it encrypted at rest? Key management?

**Expected default to verify:** all persisted state encrypted at rest with platform-managed keys.

**Note:** we don't intend to persist queries — verify this assumption holds (Check 5) AND verify the persistence we DO have (container images, secrets) is encrypted.

**Verification method:**
- [ ] Check Modal docs "Encryption."
- [ ] Confirm container images encrypted at rest.
- [ ] Confirm secrets-store encryption + access boundary.
- [ ] Document key-management posture (Modal-managed vs customer-managed).

**Blocker condition:** any persisted state including secrets is not encrypted at rest.

**Mitigation:** none acceptable — encryption-at-rest is non-negotiable for waqf-products handling user query intent.

**Result:** TBD.

### Check 5 — Scale-to-zero in-memory state termination

**Question:** When container scales to zero (Modal terminates the instance after idle period), what happens to anything held in RAM? Is there a warm-pool that retains memory across the scale-to-zero boundary? Is there any snapshot mechanism that persists in-memory state?

**Expected default to verify:** scale-to-zero fully terminates RAM; no warm-pool retains query data; no snapshot.

**Verification method:**
- [ ] Read Modal "Lifecycle" docs.
- [ ] Look for warm-pool / pre-warmed / snapshot features.
- [ ] If features exist: verify whether they apply to our container config OR can be disabled.
- [ ] Confirm: when our container goes idle past timeout, RAM goes to zero, and the next cold-start is a fresh process with no carryover.

**Blocker condition:** Modal retains in-memory state across scale-to-zero (warm-pool, snapshot, or similar) AND we can't disable it.

**Mitigation if disable-able:** disable; document in `docs/model-cards/<encoder>.md`.

**Result:** TBD.

## Overall verification report

**To populate after execution:**

```
| Check | Result | Notes | Blocker? |
|---|---|---|---|
| 1 — Query-payload logging | | | |
| 2 — Operator access boundary | | | |
| 3 — Container data residency | | | |
| 4 — Encryption-at-rest | | | |
| 5 — Scale-to-zero state termination | | | |
```

**Overall posture:** ACCEPTABLE / ACCEPTABLE WITH MITIGATIONS / BLOCKED

**If BLOCKED:** file `ARCH-AL-BAYAN-MODAL-PRIVACY-001` strategic_decisions row with the specific check that blocked + the mitigation evaluation. PAUSE EMBED_PIPELINE_v02 Phase A backfill until resolved.

**If ACCEPTABLE WITH MITIGATIONS:** document mitigations in EMBED_PIPELINE_v02 §hosting-privacy + `docs/model-cards/<encoder>.md`. Proceed.

**If ACCEPTABLE:** record in EMBED_PIPELINE_v02 §hosting-privacy with verification timestamp + Modal docs version SHA. Proceed.

## Re-verification trigger

This verification is NOT one-time. Re-execute on:
- Modal makes a material privacy posture change (announce, blog post, terms-of-service update)
- Annual review (next: 2027-04-28)
- Before any Mac Mini → v0.2.5 migration kicks off (different posture, different verification surface)

## References

- CAI-RESP-095 (decision id 567) — the ruling that mandated this verification
- CAI-RESP-094 (id 562) — the parent ruling that established self-host posture
- VISION-003 INV-2 (no riba; halal capital stack — extends to compute substrate)
- VISION-003-WAQF-01 (waqf monetisation model — drives the data-residency expectations)
- Q 49:6 fatabayyanu (verify before adopting)
- Modal docs (URL TBD when verification starts; pin SHA at execution time)

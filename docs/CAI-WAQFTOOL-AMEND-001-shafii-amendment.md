# CAI-WAQFTOOL-AMEND-001 — Shāfi'ī Amendment to WAQFTOOL-01

**Status:** DRAFT — cc-scholar input to L7 scholar-of-record cycle-1 review. PENDING signoff.
**Parent:** `docs/WAQFTOOL-01-hanafi-declaration.md` (v0), CAI-RESP-110 (madhab override + L7 pairing).
**Cycle:** L7 first ruling submission per CAI-RESP-110 Part 6 — proposed because WAQFTOOL-01 amendment is the lowest-blast-radius input on which to load-test the new scholar review pipeline (vs. INV-8 PoS-halal which is sequenced cycle 2–3).
**Reviewer:** `<L7_SCHOLAR_OF_RECORD>` (placeholder; formal onboarding doc gates name disclosure on the audit trail).
**Audit-trail filing:** `strategic_decisions` row to be inserted with `decision_ref='CAI-WAQFTOOL-AMEND-001'` ONLY after scholar signoff. Until then this is a draft cc-scholar artifact.

## Why this amendment

CAI-RESP-110 ratified L7 pairing with the named candidate, anchored Shāfi'ī (overriding cc-scholar's Hanafi proposal), arranged fi sabilillah with non-optional Part 6(iii) graceful-conversion clause. WAQFTOOL-01 v0 was authored with explicit Hanafi configuration "with explicit acknowledgement, not silently" precisely because no scholar-of-record was paired (per CAI-RESP-062 GAP 4: "option (a) [Shafi'i] requires resources that don't exist yet"). That contingency just resolved.

WAQFTOOL-01 v0 §"Trigger for migration" lists three triggers; the first has now fired:

> 1. A scholar-of-record is paired to Al-Bayān (INV-7 satisfied) **and consents to assuming mutawalli or co-mutawalli role**.

The first half of the trigger has fired (pairing per CAI-RESP-110). The second half — mutawalli-role consent — is the open fiqh question on which this amendment depends and which L7 cycle-1 review must answer.

## What this amendment does NOT do

To prevent ambiguity:

- It does **not** revoke or overwrite WAQFTOOL-01 v0. v0 is preserved in place as audit substrate (per WAQFTOOL-01 v0 §migration-path: *"this document is not revoked, it is amended in-place with the prior version preserved on-chain (pending INV-8 substrate ruling) or in the git audit log"*).
- It does **not** unilaterally commit to a specific mutawalli configuration. Three configurations are presented; scholar's call.
- It does **not** file the `strategic_decisions` row for CAI-WAQFTOOL-AMEND-001 — that filing is gated on L7 signoff via the cycle-1 review process.
- It does **not** disclose the L7 scholar's name on the audit trail. Placeholder `<L7_SCHOLAR_OF_RECORD>` until formal onboarding doc signed (per CAI-RESP-110).
- It does **not** address the wingmen-stack-default-madhab declaration in WAQFTOOL-01 (already Shāfi'ī in v0). Only the founder-mutawalli-madhab line is in scope.

## Proposed v1 declaration text

The scholar reviews and amends as needed before signoff. cc-scholar's draft proposes the following:

> **On the Madhab of the Mutawalli (v1, post-pairing)**
>
> Al-Bayān's waqf is now constituted under the Shāfi'ī position on waqf administration. The contingency that justified the v0 transparent-Hanafi declaration (no scholar-of-record paired to Al-Bayān) has resolved with the pairing of `<L7_SCHOLAR_OF_RECORD>` per CAI-RESP-110.
>
> The Shāfi'ī position on founder-mutawalli requires appointment of an independent administrator before the waqf perfects. The configuration adopted is **<CONFIGURATION-CHOSEN-BY-SCHOLAR>** (see open question §1 below). All three options below are Shāfi'ī-compatible on the fiqh face; the scholar selects on operational and amanah grounds.
>
> The wingmen-stack-default Shāfi'ī declaration (originally stated in v0 but operationally pending) is now executed. Future amendments to mutawalli configuration are filed as `CAI-WAQFTOOL-AMEND-<n>` with the same scholar review cycle.
>
> The Part 6(iii) graceful-conversion clause from CAI-RESP-110 (90-day check-in trigger conditions for the fi sabilillah arrangement converting honorably to a professional fee structure if scope creep accumulates) governs the relationship and is referenced here for transparency. The mutawalli arrangement under this declaration is independent of the L7 reviewer arrangement; either may be reconfigured without the other being affected.
>
> Public transparency dashboard (WT-5) commitments from v0 carry forward unchanged.
>
> *Signed*, Musa Bagushair (wāqif), [date]
> *Countersigned*, `<L7_SCHOLAR_OF_RECORD>` (mutawalli per chosen configuration), [date]

## Open questions for L7 scholar review (cycle-1 input)

### Q1 — Mutawalli configuration

The scholar consents to which configuration?

- **(a) Sole mutawalli (scholar).** Most Shāfi'ī-pure. Musa steps back to founder-only role. Operational risk: scholar bears administrative load and visibility scope unfamiliar to a fi sabilillah arrangement; arguably triggers Part 6(iii) graceful-conversion from day 1.
- **(b) Co-mutawalli (scholar + Musa).** Less Shāfi'ī-pure (founder retains mutawalli capacity) but Shāfi'ī-defensible if scholar holds majority decision authority on disposition; defensible-because-paired. Operationally feasible at v0.1.
- **(c) Scholar as L7 reviewer only; independent third-party mutawalli appointed separately.** Cleanest separation of fiqh-review and waqf-administration roles; requires a separate trustee recruitment which adds latency. Defers full Shāfi'ī compliance to a second milestone.

cc-scholar opinion (input only, not authoritative): (b) appears the right v0.1 choice. It honors the fi sabilillah scope (scholar's contributing time is fiqh-judgment, not administration), pairs with the Part 6(iii) graceful-conversion as the explicit honor-mechanism, and lets (a) or (c) become a later AMEND-002 trigger if/when scope warrants. Scholar may disagree.

### Q2 — Shāfi'ī conditions for waqf perfection

Are there Shāfi'ī conditions beyond independent-mutawalli appointment that v0 operations might have triggered concern under, now that we are formally Shāfi'ī-anchored? Examples to evaluate:

- **Specificity of beneficiaries:** does the v0 deed text on beneficiaries (waqf-treasury surplus disposition) need amendment to satisfy Shāfi'ī specificity standards?
- **Perpetuity:** Shāfi'ī tradition treats waqf as perpetual. v0 already affirms this; does the scholar see any latent ambiguity?
- **Disposition of corpus vs. yield:** Shāfi'ī rules on what may be drawn from waqf (yield only, not corpus). v0 transparency dashboard surfaces both; scholar reviews policy.

cc-scholar opinion (input only): no obvious gaps but I am not the qualified reviewer.

### Q3 — Treatment of existing v0 operations

Operations from waqf constitution date through this amendment date were under the transparent-Hanafi v0 configuration. Does the scholar:

- Validate them retroactively (Shāfi'ī accepts the Hanafi-permitted period as valid because it was explicitly madhab-pluralism, not concealment)?
- Require remediation (re-issuance of any disposition / re-categorization)?
- Treat the v0 period as a separate accounting epoch with its own attestation?

cc-scholar opinion: madhab-pluralism precedent (cf. Ibn Taymiyya, Shāṭibī on inter-madhab tolerance for documented good-faith madhab choice) supports option 1 — retroactive validation. But this is a fiqh call.

### Q4 — Part 6(iii) graceful-conversion linkage

Does the scholar request that Part 6(iii) trigger conditions be cross-referenced into this declaration so that any AMEND-002 around mutawalli-role compensation auto-files when 90-day check-in flags fire? Or kept as separate audit surfaces? Defaulting to separate-but-cross-referenced unless scholar requests otherwise.

## Proposed v1 machine-readable attestation

```json
{
  "waqf_name": "Al-Bayan",
  "wakif": "Musa Bagushair",
  "current_mutawalli": ["<TBD-PER-Q1>"],
  "mutawalli_madhab_position": "shafi-i-<TBD-PER-Q1>",
  "declared_reason": "Post-L7-pairing migration per CAI-RESP-110; configuration selected by scholar review",
  "wingmen_stack_default_madhab": "shafi-i",
  "v0_transition": {
    "v0_decl_path": "docs/WAQFTOOL-01-hanafi-declaration.md",
    "v0_period_start": "<v0-effective-date>",
    "v0_period_end": "<v1-signoff-date>",
    "v0_disposition_handling": "<per-Q3>"
  },
  "migration_triggers": [
    "scholar-recuses-or-graceful-converts-per-part-6-iii",
    "shafi-i-conditions-revisited-by-scholar-or-successor",
    "musa-recuses-from-co-mutawalli-role"
  ],
  "last_reviewed_at": "<L7-signoff-date>",
  "deed_version": "v1",
  "deed_supersedes": "v0",
  "dashboard_url": "https://al-bayan.{domain}/waqf/transparency",
  "l7_scholar_of_record": "<L7_SCHOLAR_OF_RECORD>",
  "l7_pairing_decision_ref": "CAI-RESP-110",
  "amendment_decision_ref": "CAI-WAQFTOOL-AMEND-001"
}
```

## Updated migration triggers (replace v0 §migration triggers)

When **any** of the following is satisfied, this declaration is amended (filed as `CAI-WAQFTOOL-AMEND-<n>`):

1. The L7 scholar recuses, withdraws, or the Part 6(iii) 90-day check-in surfaces a graceful-conversion trigger (paying institutional clients citing scholar's name in regulatory submissions, time commitment exceeding ~2hr/week sustained, or scholar discomfort).
2. Shāfi'ī conditions are revisited by the L7 scholar or a successor scholar — operational reality may have drifted from constitution-time fiqh.
3. Musa recuses from any co-mutawalli role (e.g., founder unavailable, conflict of interest declared).
4. A regulatory event (MUIS, AGC, MAS) requires re-anchoring of mutawalli configuration.

(Note: v0 trigger 3 — "Hanafi position becomes operationally untenable" — is dropped since we are no longer anchored Hanafi.)

## Acceptance criteria for cycle-1 review completion

- L7 scholar selects configuration on Q1 and signs off (paper or e-signature; cc-scholar adapts mechanics to scholar preference).
- Q2-Q4 either resolved or filed as follow-up AMEND-002+ items with explicit defer reasons.
- `CAI-WAQFTOOL-AMEND-001` strategic_decisions row inserted with chosen configuration + scholar countersignature reference + INV-8 audit-log row.
- `docs/CAI-WAQFTOOL-AMEND-001-shafii-amendment.md` updated in place to reflect ratified configuration; commit reference recorded in the strategic_decisions row.
- `docs/WAQFTOOL-01-hanafi-declaration.md` v0 receives a footer note: "**SUPERSEDED 2026-XX-XX by CAI-WAQFTOOL-AMEND-001** — preserved as audit substrate; do not edit."
- `.well-known/waqf-attestation.json` (when published) reflects v1.

Then: AMEND-001 status = `ratified`. WAQFTOOL-01 amendment trigger #1 records as executed. L7 cycle-1 closed.

## What this submission load-tests (CAI-RESP-110 cycle-1 motivation)

CAI's rationale for sequencing this as cycle-1 (per RESP-110): low blast radius, well-scoped fiqh question, exercises the full pipeline (drafting → review → signoff → strategic_decisions filing → audit-trail row → declaration update → dashboard refresh) without the existential stakes of INV-8 PoS-halal. Specifically:

- **Tests scholar review SOP:** can the scholar receive a draft, return amendments, sign off in <1 review cycle (90 min/week)?
- **Tests audit substrate:** does INV-8 hash-chain absorb a multi-doc commit (amendment + supersede note + JSON attestation) cleanly?
- **Tests Part 6(iii) clause posture:** does the scholar invoke graceful-conversion early (e.g., on Q1 selecting (a) sole-mutawalli → out-of-scope load) or accept v0.1 as scoped?

If cycle-1 reveals SOP gaps, those are filed as L7-PROCESS-001 follow-ups before cycle-2 (INV-8 PoS-halal) begins.

## References

- `docs/WAQFTOOL-01-hanafi-declaration.md` — v0 superseded surface
- CAI-RESP-110 (decision id 625) — L7 pairing + madhab override
- CAI-RESP-062 GAP 4 — original Hanafi-anchor justification (now obsolete contingency)
- VISION-003 INV-7 — pairing obligation now in execution
- VISION-003-WAQFTOOL-01 — source decision
- VISION-003-WAQF-01 (W-5, W-8) — transparency dashboard + annual waqf report
- `docs/INV-8-scholar-question.md` — note this amendment exercises the scholar review pipeline that PoS-halal cycle-2/3 depends on
- `feedback_cc_challenges_cai.md` — why cc-scholar drafts but does not author Ihsan-level fiqh decisions

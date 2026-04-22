# Al-Bayān Waqf Deed — Madhab Selection Declaration

**Status:** draft for Phase 1 deed finalization
**Parent:** VISION-003-WAQFTOOL-01 + CAI-RESP-062 (option (b) accepted: transparent Hanafi declaration)
**Publication surface:** Al-Bayān transparency dashboard (waqf constraint WT-5) + `waqfiyyah.md` public deed excerpt + `.well-known/waqf-attestation.json` machine-readable

## The declaration (to be included in the deed and on the transparency dashboard)

> **On the Madhab of the Founder-Mutawalli**
>
> Al-Bayān's waqf is constituted under the Hanafi position that permits the founder (wāqif) to act as mutawalli (administrator) of the waqf he endows, without requiring appointment of an independent administrator at the moment of constitution.
>
> The Wingmen stack's declared default madhab across its software systems is Shāfi'ī. The Shāfi'ī position on founder-mutawalli requires appointment of an independent administrator before the waqf perfects. Under that default, the current configuration — Musa Bagushair as founder, sole mutawalli, sole operator of Al-Bayān at constitution — would not satisfy Shāfi'ī conditions for validity.
>
> We are choosing Hanafi configuration **with explicit acknowledgement**, not silently. The reasons are:
>
> 1. **Phase-1 logistics.** No scholar-of-record is yet paired to Al-Bayān (VISION-003 INV-7 is an open obligation, not a satisfied condition). Until pairing lands, appointing a truly-independent administrator would either be nominal (a friend signs) — which would be the exact failure mode the Shāfi'ī rule exists to prevent — or delayed indefinitely, which would block the deed itself and leave Al-Bayān without the capital structure INV-2 (halal) and W-3 (surplus-to-waqf-treasury) require.
>
> 2. **Madhab-pluralism is valid.** Hanafi founder-mutawalli is a classical permission supported by Imam Abū Ḥanīfa, Muḥammad al-Shaybānī, and the subsequent Hanafi tradition. It is not a concession or a workaround; it is one of the four Sunni schools' positions. Choosing it explicitly, with the reasoning published, is madhab-honest. Silently using it under a declared Shāfi'ī default is not.
>
> 3. **Transparency compensates for madhab divergence.** The public transparency dashboard (WT-5) shows every disbursement, every scholar payment, every corpus addition, every founder-compensation line. Any classical concern the Shāfi'ī rule tries to mitigate (concealment, drift, founder-benefit) is countered by per-transaction public audit — a disclosure regime stronger than anything the classical scholars had available.
>
> 4. **Migration path committed.** Once a scholar-of-record is paired to Al-Bayān per INV-7, we will evaluate appointing that scholar (or a nominated independent trustee) as co-mutawalli or sole mutawalli under a Shāfi'ī-compatible configuration, provided the scholar consents. At that point the declaration is updated to reflect the new arrangement; this document is not revoked, it is amended in-place with the prior version preserved on-chain (pending INV-8 substrate ruling) or in the git audit log (fallback per INV-8-postgres-merkle-fallback.md).
>
> This declaration is itself an object of accountability: if in future practice Al-Bayān's waqf operates in ways that violate Hanafi conditions for founder-mutawalli (private benefit, non-transparent disposition, departure from stated purposes), the same transparency dashboard will surface the violation, and any user, scholar, or beneficiary has standing to raise it publicly.
>
> *Signed*, Musa Bagushair (wāqif), [date]
> *Countersigned (pending)*, scholar-of-record [to-be-paired], [date]

## Trigger for migration to Shāfi'ī-compatible configuration

When **any** of the following is satisfied, this declaration is amended:

1. A scholar-of-record is paired to Al-Bayān (INV-7 satisfied) and consents to assuming mutawalli or co-mutawalli role.
2. An independent trustee is nominated by the founder and separately consents (Al-Bayān transparency dashboard documents the nomination and consent).
3. The Hanafi position becomes operationally untenable (Singapore regulatory constraint, MUIS policy change, etc.) and the Shāfi'ī path becomes logistically feasible.

In cases (1) and (2), the configuration change + updated declaration are filed to `strategic_decisions` under `AL-BAYAN-WAQF-MUTAWALLI-<n>` and published on WT-5.

## Machine-readable attestation (for `.well-known/waqf-attestation.json`)

```json
{
  "waqf_name": "Al-Bayan",
  "wakif": "Musa Bagushair",
  "current_mutawalli": ["Musa Bagushair"],
  "mutawalli_madhab_position": "hanafi-founder-mutawalli",
  "declared_reason": "Phase 1 constitution pre-scholar-of-record pairing; transparency dashboard compensates",
  "wingmen_stack_default_madhab": "shafi-i",
  "migration_triggers": [
    "scholar-of-record-paired-and-consents",
    "independent-trustee-nominated-and-consents",
    "hanafi-path-untenable"
  ],
  "last_reviewed_at": "2026-04-22",
  "deed_version": "v0",
  "dashboard_url": "https://al-bayan.{domain}/waqf/transparency"
}
```

## WT-5 dashboard section (spec)

The transparency dashboard includes a "Madhab & Governance" tab showing:

- Current mutawalli(s) with names and roles (founder, co-mutawalli, scholar-of-record).
- Declared Hanafi configuration with inline link to this document.
- Countdown to next annual review.
- All prior declarations (v0, v1, ...) with diff view.
- Any raised public concerns (issue tracker on `al-bayan/waqf-governance` GitHub repo) — public, un-moderatable by Al-Bayān operators.

## References

- VISION-003-WAQFTOOL-01 — source decision
- CAI-RESP-062 — option (b) transparent Hanafi accepted
- VISION-003-WAQF-01 (W-5, W-8) — transparency dashboard + annual waqf report requirements
- VISION-003 INV-7 — scholar-of-record pairing (migration trigger 1)
- INV-8-scholar-question.md — audit-trail substrate for this declaration's amendment history
- Hanafi references: al-Mabsūṭ (Sarakhsī), al-Hidāya (al-Marghīnānī) on waqf chapter
- Shāfi'ī references: al-Umm (al-Shāfi'ī), al-Muhadhdhab (al-Shīrāzī) on waqf chapter

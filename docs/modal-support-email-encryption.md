# Modal Support Email — Encryption-at-Rest Verification (CHECK 4)

**Status:** Draft. Musa to review, paste into Modal support channel, send.
**Source:** docs/MODAL_PRIVACY_VERIFICATION.md CHECK 4 — encryption-at-rest is non-negotiable; mitigation only via verified-and-documented posture.
**Why a support email (not docs only):** Modal's public docs cover encryption at a marketing level; the verification we need is granular (key management, customer-managed-key option, secret-store boundary) and is the kind of question best answered by a written response from Modal staff that we can archive into the verification record.

---

## Subject

`Encryption-at-rest verification questions for our use case (Al-Bayān, ai-scholar)`

## Body

Hello Modal team,

We're evaluating Modal as the managed-compute substrate for an Islamic-knowledge retrieval product (Al-Bayān). Our verification protocol requires a documented answer on encryption-at-rest before we provision in earnest. Could you confirm the following, in writing, so we can archive your response in our compliance record?

**1. Container images**
Are container images stored encrypted at rest? If yes, who manages the encryption keys (Modal-managed, cloud-provider-managed, or customer-managed-key option available)?

**2. Secrets store**
For values stored via Modal's secrets feature (env-var injection at container start), is the underlying store encrypted at rest? What is the access boundary — which Modal staff roles can read decrypted values, and under what circumstances?

**3. Logs**
For any logs Modal retains (request logs, stdout/stderr, metric streams), are they encrypted at rest? What is the retention period, and is there an option to disable retention or shorten it?

**4. Snapshots / warm pools**
If Modal retains any snapshot of container memory, filesystem, or process state across invocations (warm pool, pre-warm, fast-cold-start mechanisms), is that retained state encrypted at rest? Can it be disabled per-app?

**5. Customer-managed keys (CMK)**
Is there an option to bring our own key (BYOK / CMK) for any of the above categories, on any plan tier? If yes, please share the relevant docs link or process.

**6. SOC 2 / ISO 27001 attestation**
Could you share the most recent SOC 2 Type II report (or ISO 27001 certificate) covering the encryption-at-rest control objective? We're happy to sign an NDA if needed.

**7. Key rotation**
For Modal-managed keys, what is the rotation cadence and rotation procedure? Is rotation transparent to running workloads?

## Context (for triage)

- Use case: managed inference of an open-weights embedding model (BGE-M3, ~2 GB) over a public-domain corpus. We do not intend to persist user query data.
- Region preference: APAC (Singapore-adjacent if available) to align with our user base data-residency expectations.
- Volume estimate: low — this is a v0.2 verification phase, not high-traffic production.

## Sender notes

- Send from the email tied to the (forthcoming) Modal account so support can correlate. If account isn't provisioned yet, send from `musa.bagushair@gmail.com` and note that account provisioning is in progress.
- Archive Modal's response into `docs/MODAL_PRIVACY_VERIFICATION.md` CHECK 4 result section, including timestamp + the docs URL/SHA Modal cites.
- If Modal answers anything as "no" or "platform-managed only with no customer option" on items 1, 2, or 4 — that is the BLOCKER trigger per docs/MODAL_PRIVACY_VERIFICATION.md CHECK 4 ("none acceptable — encryption-at-rest is non-negotiable for waqf-products handling user query intent"). File `ARCH-AL-BAYAN-MODAL-PRIVACY-001` and PAUSE.

## References

- docs/MODAL_PRIVACY_VERIFICATION.md (the full 5-check protocol)
- CAI-RESP-095 (A) — the ruling that mandates this verification
- VISION-003 INV-2 — no riba / halal capital stack extends to substrate posture

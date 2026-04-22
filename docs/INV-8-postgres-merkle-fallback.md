# INV-8 Audit-Trail Substrate — Postgres + Git Merkle Fallback

**Status:** Ready to implement as v0.1 substrate
**Parent:** VISION-003 INV-8, CAI-RESP-062
**Relation to INV-8-scholar-question.md:** this is the substrate Al-Bayān ships under until the PoS halal ruling lands. Positive ruling → optional later migration to Solana anchoring. Negative ruling → this remains canonical.

## Audit properties INV-8 requires

1. **Append-only.** A ruling, once emitted, cannot be silently deleted or edited.
2. **Tamper-evident.** Any retroactive modification is detectable by any verifier using only public information.
3. **Externally witnessed.** The audit log exists somewhere Al-Bayān cannot unilaterally rewrite.
4. **Permissionlessly verifiable.** Any third party can verify a published ruling's authenticity given its content + Al-Bayān's public signing key + a commit hash.

Solana satisfies these via blockchain consensus. The fallback satisfies them via git-host replication + Ed25519 signatures.

## Design

### Table

```sql
CREATE TABLE ruling_audit_log (
  id              bigserial PRIMARY KEY,
  ruling_id       uuid NOT NULL,           -- foreign key to mizan_interactions or bayan_rulings
  content_hash    text NOT NULL,           -- SHA-256 of canonical serialized ruling content
  prev_hash       text NOT NULL,           -- content_hash of id-1; genesis = 64 zeros
  merkle_leaf     text NOT NULL,           -- SHA-256(content_hash || prev_hash || id || created_at)
  signed_by       text NOT NULL,           -- key id (rotates; old keys archived in key_registry)
  signature       text NOT NULL,           -- Ed25519 over merkle_leaf
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX ruling_audit_log_ruling_id_idx ON ruling_audit_log (ruling_id);
CREATE INDEX ruling_audit_log_created_at_idx ON ruling_audit_log (created_at DESC);

-- Append-only enforcement
REVOKE UPDATE, DELETE ON ruling_audit_log FROM PUBLIC, anon, authenticated, service_role;
CREATE RULE ruling_audit_log_no_update AS ON UPDATE TO ruling_audit_log DO INSTEAD NOTHING;
CREATE RULE ruling_audit_log_no_delete AS ON DELETE TO ruling_audit_log DO INSTEAD NOTHING;
```

### Hash chain

Every row's `prev_hash` equals the previous row's `content_hash`. Chain breakage anywhere in the log is detectable by a full re-traversal. Genesis row uses `prev_hash = '0' * 64`.

### Merkle root publication

Nightly cron (03:00 UTC):

1. Compute Merkle root of all `merkle_leaf` values in `ruling_audit_log` using SHA-256 balanced binary tree.
2. Sign root with Al-Bayān Ed25519 audit key (separate from payment/operational keys).
3. Publish `{date, row_count_last, root_hash, root_signature, key_id}` to a public git repository (`al-bayan/audit-attestations`) as a single commit, one file per day (`attestations/2026/04/22.json`).
4. GitHub signs the commit with their standard DKIM; Al-Bayān signs with Ed25519 — two independent witnesses. (Codeberg / self-hosted mirror for redundancy, rsync'd after each commit.)

The git repository is mirrored on:
- GitHub (primary)
- Codeberg (secondary, EU-hosted)
- Self-hosted mirror (on the IhsanOS Mac Mini, per ARCH-030 when cutover lands)

### Verification

Any third party can:
1. Clone `al-bayan/audit-attestations`.
2. Pick any date.
3. Verify the Ed25519 signature on the root using Al-Bayān's published audit pubkey.
4. Request the underlying ruling rows via the public API endpoint (`GET /v1/audit/ruling/{ruling_id}`).
5. Reconstruct the Merkle proof locally; confirm the ruling's `merkle_leaf` is included in the signed root.
6. Traverse the hash chain; confirm continuity.

Retroactive edit to any prior row changes its `merkle_leaf` → breaks the Merkle root → breaks every signed attestation since. Because the attestations are git-committed publicly, rewriting them after the fact is visible to any clone.

## Key management

- Signing key: Ed25519. Private key lives in `ORCHESTRATOR_AUDIT_SIGNING_KEY` env on the orchestrator only; never in application-pod env.
- Public key: published at `https://al-bayan.{domain}/.well-known/audit-key.json` alongside key-id and rotation history.
- Rotation: annual; old public keys retained in `key_registry` table with validity window.
- Loss of private key: documented incident response — rotate public key, attest at the new key, note the incident in the next attestation file. Historical attestations remain verifiable under the old (now-retired) public key.

## Cost comparison vs Solana

| Dimension | Solana | Postgres + Git |
|---|---|---|
| Per-ruling cost | ~$0.00025 at SOL=$100 | ~$0 (already in infra) |
| Trust assumption | PoS validator honesty + consensus | Git host + Ed25519 key + nightly cron uptime |
| External witness | Blockchain nodes worldwide | GitHub, Codeberg, self-hosted mirror |
| Revocation possible | No | No (inherits git append-only semantics; force-pushes to attestation repo forbidden at branch protection) |
| Halal question | Open (INV-8-scholar-question.md) | None identified |

## Implementation sequence

1. Migration: `supabase/migrations/YYYYMMDD_00X_ruling_audit_log.sql` — table + append-only rules + RLS (read: anon; write: service_role only).
2. Signing key provisioning: `scripts/audit/generate-signing-key.ts` — generates Ed25519 keypair, emits private-key install instruction + public-key JSON for .well-known.
3. Write path: hook into ruling emission (from `mizan_interactions` insert trigger or application-code path) — computes content_hash + prev_hash + merkle_leaf + signature, inserts row.
4. Nightly attestation cron: `scripts/audit/publish-daily-attestation.ts` — computes Merkle root, signs, commits to `al-bayan/audit-attestations` repo.
5. Verification endpoint: `supabase/functions/audit-verify/index.ts` — returns ruling row + Merkle proof for any `ruling_id`.
6. Published docs: `https://al-bayan.{domain}/docs/audit.md` — explains the substrate in plain language for any user or scholar wishing to verify a ruling.

## Open questions (implementer's discretion, not blockers)

- Merkle tree format: binary balanced vs Merkle DAG (Certificate Transparency-style). Binary-balanced is simpler; CT-style allows sparse historical proofs. Default: binary-balanced for v0.1.
- Attestation cadence: nightly is the baseline. Consider per-ruling real-time attestation if low-latency verification becomes a product requirement (tradeoff: git-commit volume).
- Archival: old attestations are retained forever (amanah). No rotation or pruning.

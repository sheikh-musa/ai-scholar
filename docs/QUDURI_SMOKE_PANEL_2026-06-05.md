# Post-Quduri ingestion smoke-test panel

**Run order:** translate → DB persist → embedding backfill → `/madhhab hanafi` → these queries.

**Goal:** verify that on Hanafi-distinct fiqh questions, the bot now retrieves Quduri verbatim (not just refuses with school-mismatch), and that `/madhhab hanafi` reranks ikhtilaf toward Hanafi positions where the corpus supports it.

## Test panel (6 queries)

Each query is chosen to exercise a *Hanafi-specific* position vs Shafiʿī, so retrieval routing is observable.

### 1. **"what nullifies wudu in the hanafi school"**

- **Expected Shafiʿī answer:** skin-to-skin contact nullifies (per Safīnat / Nihāyat).
- **Expected Hanafi answer:** skin-to-skin contact does NOT nullify; what nullifies is what exits from the two passages, blood/pus exiting elsewhere, sleep without seated firmness, loss of intellect, qahqaha (loud laughter) in salah-with-ruku.
- **Pass criteria:** retrieves Quduri's enumeration verbatim with attribution "Mukhtaṣar al-Qudūrī"; does NOT silently fall back to Shafiʿī rows.

### 2. **"how should I perform tayammum"**

- **Hanafi-specific:** two strikes (one face, one arms to elbows); permitted with everything of "jins al-arḍ" (sand, stone, gypsum, lime) per Abū Ḥanīfa + Muḥammad; Abū Yūsuf restricts to soil+sand only — Quduri surfaces this ikhtilaf within the school.
- **Pass:** Quduri tayammum baab retrieved; the Abū Ḥanīfa-Abū Yūsuf-Muḥammad triadic disagreement appears.

### 3. **"can I wipe over socks (jawrabayn) in salah"**

- **Hanafi position:** Abū Ḥanīfa originally rejected wiping over socks (only khuffayn); Abū Yūsuf + Muḥammad permitted for thick socks that don't pass water.
- **Pass:** Quduri's specific Hanafi internal ikhtilaf on jawrabayn surfaces; the bot doesn't conflate with Shafiʿī's blanket permission.

### 4. **"what is the minimum amount of water for a well to be tahir if najis falls in"**

- **Hanafi-distinctive:** the small-animal-corpse dalw-count rules (20-30 buckets for mouse/sparrow; 40-60 for pigeon/chicken; full bail for dog/sheep/human). This is unique to the Hanafi madhhab — Shafiʿī uses the 2-qulla rule.
- **Pass:** Quduri's bucket-count enumeration retrieved verbatim.

### 5. **"what makes a slaughter halal"**

- **Hanafi position:** Quduri treats this in Kitāb al-Dhabāʾiḥ. Hanafi position is distinct on basmala (obligatory; deliberate omission invalidates the slaughter — opposite of the Shafiʿī position which holds it sunnah-mustahabb).
- **Pass:** ikhtilaf surfaced; Quduri's stance on basmala-as-shart retrieved.

### 6. **"is laughing during salah a problem"** (control case)

- **Hanafi-distinctive:** Quduri lists *qahqaha* (loud laugh) as nullifying both salah AND wudu — uniquely Hanafi. Shafiʿī treats it as breaking only salah, not wudu.
- **Pass:** the WUDU-breaking effect appears specifically for Hanafi.

## Verification commands

After translation+embed completes:

```bash
# 1. Apply mizan_user_prefs migration manually OR test via file-based path
#    Set fake user's madhhab to hanafi:
echo '{"a8b58bd96e2f473b8af7b3978ef9aecc...": {"madhhab":"hanafi","updated_at":"2026-06-05T..."}}' > ~/.mizan_user_prefs.json

# 2. Run each query through the e2e harness with madhhab=hanafi
for Q in "what nullifies wudu in the hanafi school" \
         "how should I perform tayammum" \
         "can I wipe over socks in salah" \
         "what is the minimum water amount for a well to stay tahir" \
         "what makes a slaughter halal in the hanafi school" \
         "is laughing during salah a problem"; do
  python3 scripts/test_mizan_bot_e2e.py --query "$Q"
done
```

## What to look for in the audit rows

For each test query:
- `retrieval_ids` count should be ≥1, with at least one Quduri ID (`fa24432e-6641-4167-9151-1fc756e57429`) present.
- `output_tier` should be `quoted` or `paraphrased` (not `ai-generated` — the corpus now answers these).
- Response body should contain "*Mukhtaṣar al-Qudūrī*" verbatim attribution.
- Should NOT contain the school-mismatch refusal pattern from before (e.g., "the only fiqh matn my corpus retrieves is Shāfiʿī").

## If the smoke fails

| Failure mode | Diagnosis | Fix |
|---|---|---|
| Quduri rows not in retrieval | embeddings missing or rank threshold too high | re-run backfill; check rank against fiqh_semantic threshold (0.45) |
| Retrieves Quduri but answers in Shafiʿī voice | madhhab guidance not threading through ask_claude | verify `get_user_madhhab(telegram_id)` returns "hanafi" |
| Returns Shafiʿī Safīnat instead of Quduri | per_text_id diversification cap pulling wrong source | tighten `max_per_text_id` per madhhab in fiqh_semantic, OR add an explicit madhhab filter |
| All 6 hit `output_tier='ai-generated'` | retrieval works but matn isn't surfaced | check system prompt's "WHENEVER FIQH MATCHED PASSAGES" rule still applies to Hanafi rows |

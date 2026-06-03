-- mizan_user_prefs — per-user preferences keyed by sha256(telegram_id)
--
-- Initial schema: just madhhab preference. Other prefs (preferred_language,
-- preferred_tafsir, etc.) can be added as columns later without migration
-- of existing rows.
--
-- Why a dedicated table (not a column on mizan_interactions): interactions
-- are append-only per query; prefs are mutable per user. Keeping them
-- separate avoids touching the audit log when a user updates their madhhab.

CREATE TABLE IF NOT EXISTS public.mizan_user_prefs (
  telegram_id_hash text PRIMARY KEY,
  madhhab          text CHECK (madhhab IN ('shafii', 'hanafi', 'maliki', 'hanbali')),
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

-- Auto-bump updated_at on any row change. No-op INSERT collisions handled
-- by ON CONFLICT in the upsert path (mizan_bot uses Prefer: resolution=
-- merge-duplicates).
CREATE OR REPLACE FUNCTION public.mizan_user_prefs_touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS mizan_user_prefs_touch ON public.mizan_user_prefs;
CREATE TRIGGER mizan_user_prefs_touch
  BEFORE UPDATE ON public.mizan_user_prefs
  FOR EACH ROW
  EXECUTE FUNCTION public.mizan_user_prefs_touch_updated_at();

-- RLS: service_role only (mizan_bot uses service role; users don't query
-- this table directly).
ALTER TABLE public.mizan_user_prefs ENABLE ROW LEVEL SECURITY;

-- No policies defined → no anon/authenticated access. service_role bypasses
-- RLS by default.

COMMENT ON TABLE  public.mizan_user_prefs IS
  'Per-user preferences keyed by sha256(telegram_id). Reset via /clear command does NOT clear prefs.';
COMMENT ON COLUMN public.mizan_user_prefs.madhhab IS
  'User-declared school for ikhtilaf re-ranking. NULL means no preference (default Shafi-i corpus surfacing).';

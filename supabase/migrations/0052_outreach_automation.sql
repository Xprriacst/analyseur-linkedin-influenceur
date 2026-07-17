-- ALE-284 (V1, phase 1) — réglages d'auto-prospection sur le compte outreach.
--
-- Contexte : jusqu'ici chaque invitation demande un clic du client (il choisit QUI
-- contacter, le moteur cadencé d'ALE-174 choisit QUAND). Cette V1 ajoute un mode
-- « prospection automatique » : le client donne son accord UNE fois (opt-in
-- explicite), et un cron déposera les invitations dans la file tout seul, pour les
-- leads dépassant un seuil de score.
--
-- Cette phase ne pose QUE les réglages (le consentement + les bornes). Le cron
-- d'auto-invitation qui les lit arrive dans la phase suivante : tant qu'il n'existe
-- pas, ces colonnes sont inertes (aucun envoi automatique).
--
-- Idempotente (IF NOT EXISTS). Le score de lead est sur 0-100 (migration 0042) :
-- `auto_invite_min_score` est sur la même échelle (défaut 70 = uniquement les leads
-- bien qualifiés — un compte neuf qui inviterait tous ses leads verrait son taux
-- d'acceptation, et donc son risque de restriction, exploser).

alter table public.linkedin_outreach_accounts
  add column if not exists auto_prospection_enabled   boolean  not null default false,
  add column if not exists auto_invite_min_score       smallint not null default 70,   -- 0-100, échelle du score de lead (0042)
  add column if not exists auto_invite_daily_cap       smallint not null default 15,   -- plafond des invitations AUTO déposées/jour (borné en plus par le warm-up + plafonds durs d'ALE-174)
  add column if not exists auto_first_message_enabled  boolean  not null default false; -- brouillon de 1er message auto (phase 3) ; inerte tant que la phase 3 n'est pas là

-- Ces colonnes sont réglées par le client depuis l'app → il faut le droit UPDATE
-- dessus. La migration 0048 a RÉVOQUÉ l'UPDATE global sur cette table et le re-donne
-- colonne par colonne ; une colonne absente de cette liste casse silencieusement
-- l'upsert du compte (Postgres exige UPDATE sur CHAQUE colonne du payload) — piège
-- documenté dans le changelog. Aucun trou de sécurité : la RLS
-- (`with check auth.uid() = user_id`) empêche d'écrire sur la ligne d'un autre.
grant update (
  auto_prospection_enabled,
  auto_invite_min_score,
  auto_invite_daily_cap,
  auto_first_message_enabled
) on public.linkedin_outreach_accounts to authenticated;

comment on column public.linkedin_outreach_accounts.auto_prospection_enabled is
  'Opt-in explicite : le client autorise l''envoi automatique d''invitations en son nom (ALE-284).';
comment on column public.linkedin_outreach_accounts.auto_invite_min_score is
  'Score minimum (0-100) pour qu''un lead soit invité automatiquement.';
comment on column public.linkedin_outreach_accounts.auto_invite_daily_cap is
  'Plafond d''invitations auto déposées en file par jour (le warm-up et les plafonds durs d''ALE-174 s''appliquent en plus).';
comment on column public.linkedin_outreach_accounts.auto_first_message_enabled is
  'Génère un brouillon de 1er message à valider dans l''inbox après acceptation (phase 3).';

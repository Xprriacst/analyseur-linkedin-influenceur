-- 0052 — Prospection automatique, « Autopilote » (ALE-284, epic ALE-226)
--
-- Contexte : jusqu'ici, contacter un lead demande DEUX clics humains — « Inviter »,
-- puis « Envoyer le message » une fois l'invitation acceptée. Le client choisit QUI
-- (son clic) et le moteur cadencé d'ALE-174 choisit QUAND. Résultat : la prospection
-- s'arrête dès que le client ne se connecte pas. Et depuis la détection automatique
-- d'acceptation (0051), un lead peut passer « en relation » sans que rien n'enchaîne.
--
-- L'autopilote déplace le consentement : le client donne son accord UNE fois, pour une
-- SUITE d'envois, en réglant trois choses dans une pop-up :
--   1. à QUI on écrit          → `auto_invite_min_score` (seuil de score ICP)
--   2. QUOI on écrit           → `auto_message_mode` (aucun message / IA / template)
--   3. avec ou sans RELECTURE  → `auto_message_requires_validation`
--
-- ⚠️ Changement de nature, à traiter comme tel : ALE-174 ne faisait que DÉCALER ce que
-- le client avait lui-même demandé. Ici, des messages partent sans clic sur chaque
-- envoi. D'où : opt-in explicite (`auto_prospection_enabled`, défaut false), relecture
-- ACTIVÉE par défaut, et aucun réglage implicite (rien ne part tant que la pop-up n'a
-- pas été ouverte et validée).
--
-- ⚠️ Contrainte d'architecture n°1 : l'autopilote n'envoie RIEN lui-même. Il ne fait que
-- DÉPOSER des actions dans la file d'ALE-174 (`linkedin_outreach_queue`), que le moteur
-- sort au bon moment. Le warm-up, la plage horaire, le délai aléatoire, les plafonds et
-- le gel s'appliquent donc gratuitement. Un autopilote qui appellerait Unipile en direct
-- contournerait tous les garde-fous anti-restriction.
--
-- Idempotente (IF NOT EXISTS). Le score de lead est sur 0-100 (migration 0042).

-- ── 1. Réglages de l'autopilote, portés par le compte de prospection ─────────────

alter table public.linkedin_outreach_accounts
  -- Opt-in explicite. Tant que c'est false, RIEN n'est déposé en file automatiquement.
  add column if not exists auto_prospection_enabled boolean not null default false,

  -- À QUI. Seuil sur le score ICP 0-100 (migration 0042). Les trois choix de la pop-up
  -- (vert / vert+orange / tous) sont exactement les trois paliers de couleur DÉJÀ
  -- affichés sur les pastilles de la liste de leads (frontend `scoreColor`) :
  -- 70 = vert, 40 = vert+orange, 0 = tous. Réutiliser ces seuils-là n'est pas un détail :
  -- si « vert » dans la pop-up ne désignait pas les mêmes leads que les pastilles vertes
  -- de la liste, le client réglerait son autopilote sur autre chose que ce qu'il voit.
  -- Défaut 70 (vert seul) : un compte qui inviterait tous ses leads verrait son taux
  -- d'acceptation chuter, et c'est ce taux qui décide du risque de restriction LinkedIn.
  add column if not exists auto_invite_min_score smallint not null default 70,

  -- Plafond des invitations AUTO déposées par jour. Le warm-up et les plafonds durs
  -- d'ALE-174 s'appliquent EN PLUS : c'est un plafond, jamais un objectif.
  add column if not exists auto_invite_daily_cap smallint not null default 15,

  -- QUOI. 'none' = on se contente de la demande de connexion (aucun message) ;
  -- 'ai' = message rédigé par l'IA lead par lead ; 'template' = le texte ci-dessous,
  -- variables du lead substituées.
  add column if not exists auto_message_mode text not null default 'none',

  -- Texte du template quand `auto_message_mode` = 'template'. Variables acceptées :
  -- {{prenom}} {{nom}} {{titre}} — substitution dans `src/outreach_autopilot.py`.
  add column if not exists auto_message_template text,

  -- RELECTURE. true = le message est déposé en `draft` et attend la validation du
  -- client ; false = il entre directement en file. Défaut true, et l'app recommande de
  -- le garder pour les messages IA : c'est le seul garde-fou contre un message
  -- maladroit envoyé à cinquante personnes au nom du client.
  add column if not exists auto_message_requires_validation boolean not null default true;

-- Un mode de message inconnu ferait silencieusement « aucun message » côté moteur :
-- on préfère que la base refuse la valeur.
alter table public.linkedin_outreach_accounts
  drop constraint if exists linkedin_outreach_accounts_auto_message_mode_check;
alter table public.linkedin_outreach_accounts
  add constraint linkedin_outreach_accounts_auto_message_mode_check
  check (auto_message_mode in ('none', 'ai', 'template'));

-- Colonne d'une version antérieure de ce lot (booléen « 1er message auto »), remplacée
-- par `auto_message_mode` qui porte les TROIS cas au lieu de deux. Elle n'a jamais existé
-- ailleurs que sur la base de dev (la PR n'a pas été mergée, aucun code en vol ne la
-- lit) : rien à préserver, et la laisser serait une colonne morte trompeuse.
alter table public.linkedin_outreach_accounts
  drop column if exists auto_first_message_enabled;

-- Ces colonnes sont réglées par le client depuis l'app → il lui faut le droit UPDATE
-- dessus. ⚠️ La migration 0048 a RÉVOQUÉ l'UPDATE global sur cette table et le redonne
-- colonne par colonne : une colonne absente de cette liste casse SILENCIEUSEMENT
-- l'upsert du compte (Postgres exige UPDATE sur CHAQUE colonne du payload). Aucun trou
-- de sécurité : la RLS (`with check auth.uid() = user_id`) interdit d'écrire la ligne
-- d'un autre. `frozen` reste volontairement hors de cette liste — le client ne doit pas
-- pouvoir se dégeler lui-même, ce serait son premier réflexe et le pire.
grant update (
  auto_prospection_enabled,
  auto_invite_min_score,
  auto_invite_daily_cap,
  auto_message_mode,
  auto_message_template,
  auto_message_requires_validation
) on public.linkedin_outreach_accounts to authenticated;

-- ── 2. File d'envoi : d'où vient l'action, et brouillons à valider ───────────────

alter table public.linkedin_outreach_queue
  -- 'manual' = le client a cliqué ; 'autopilot' = déposé par le planificateur.
  -- Sert au plafond d'invitations auto/jour et à l'affichage (« déposé par l'autopilote »).
  add column if not exists origin text not null default 'manual';

alter table public.linkedin_outreach_queue
  drop constraint if exists linkedin_outreach_queue_origin_check;
alter table public.linkedin_outreach_queue
  add constraint linkedin_outreach_queue_origin_check
  check (origin in ('manual', 'autopilot'));

-- Statut `draft` : message rédigé par l'autopilote, EN ATTENTE de la validation du
-- client. ⚠️ C'est la garantie de sécurité centrale de ce lot : le moteur d'envoi ne lit
-- QUE les actions `pending` (`db.admin_due_queue_items` filtre `status='pending'`), donc
-- un brouillon est structurellement inenvoyable tant que le client n'a pas approuvé.
-- Ce n'est pas une politesse du code applicatif : c'est le filtre de la requête qui le
-- tient hors de la file.
--
-- La 0048 pose déjà un index unique sur (lead_id, action_type) where status='pending'
-- (anti-double-clic). Il faut le même sur les brouillons, sinon deux passages du
-- planificateur empileraient deux brouillons pour le même lead.
create unique index if not exists uniq_linkedin_outreach_queue_draft
  on public.linkedin_outreach_queue(lead_id, action_type)
  where status = 'draft';

-- Le planificateur cherche « les actions déjà connues pour ce lead », tous statuts
-- confondus, pour ne jamais reproposer une action déjà envoyée, en file ou refusée.
create index if not exists idx_linkedin_outreach_queue_lead
  on public.linkedin_outreach_queue(user_id, lead_id, action_type, status);

comment on column public.linkedin_outreach_accounts.auto_prospection_enabled is
  'Opt-in explicite : le client autorise l''app à déposer des actions en son nom (ALE-284).';
comment on column public.linkedin_outreach_accounts.auto_invite_min_score is
  'Score ICP minimum (0-100) pour inviter automatiquement. 70 = vert, 40 = vert+orange, 0 = tous.';
comment on column public.linkedin_outreach_accounts.auto_invite_daily_cap is
  'Plafond d''invitations auto déposées par jour (warm-up et plafonds durs d''ALE-174 en plus).';
comment on column public.linkedin_outreach_accounts.auto_message_mode is
  'none = demande de connexion seule | ai = message rédigé par l''IA | template = texte à variables.';
comment on column public.linkedin_outreach_accounts.auto_message_requires_validation is
  'true = le message attend la relecture du client (statut draft, inenvoyable par le moteur).';
comment on column public.linkedin_outreach_queue.origin is
  'manual = clic du client | autopilot = déposé par le planificateur (ALE-284).';

-- 0075 — le compte LinkedIn (Unipile) d'un client ne peut plus être capté par un autre
--
-- FAILLE CORRIGÉE (audit sécurité 2026-09-09). Une seule clé API Unipile sert
-- TOUS les clients : le cloisonnement repose entièrement sur la colonne
-- `unipile_account_id`. Deux chemins permettaient de s'approprier le compte
-- LinkedIn d'un autre client — donc de lire sa messagerie et d'envoyer des
-- invitations et des messages en son nom :
--
--   1. ÉCRITURE DIRECTE. La 0043 accorde `insert/update/delete` à `authenticated`
--      et la 0048 n'a resserré que l'UPDATE, en laissant `unipile_account_id`
--      dans la liste des colonnes autorisées. Avec la clé anon (publique) et son
--      propre JWT, un client écrivait l'`unipile_account_id` d'autrui sur sa
--      ligne. Le `insert`/`delete` restés ouverts permettaient en prime de
--      SUPPRIMER puis RECRÉER sa ligne — ce qui remettait `frozen` à false et
--      `warmup_started_at` à zéro, contournant le gel anti-restriction et le
--      warm-up que la 0048 était censée rendre incontournables.
--
--   2. REPLI DE RATTACHEMENT. `GET /accounts` d'Unipile ne renvoie pas notre
--      `name` (= user_id), donc `/me/linkedin/outreach/refresh` retombait sur
--      « le compte le plus récent non encore réclamé en base ». Or la
--      déconnexion SUPPRIMAIT la ligne sans délier le compte chez Unipile : le
--      compte redevenait « non réclamé » alors qu'il était toujours connecté.
--      Le prochain `refresh` de n'importe quel client se l'attribuait.
--
-- Ce que pose cette migration :
--   (a) le retrait des droits d'écriture au client est dans la 0076, PAS ici —
--       voir l'ordre de déploiement ci-dessous ;
--   (b) un journal PERMANENT des rattachements : un compte Unipile revendiqué
--       une fois ne redevient jamais « libre », même après déconnexion ;
--   (c) `connect_requested_at`, qui borne le repli aux comptes créés APRÈS que
--       CE client a demandé son lien d'authentification.
--
-- ⚠️ ORDRE DE DÉPLOIEMENT — c'est la raison d'être du découpage 0075/0076.
-- La 0075 (celle-ci) n'enlève RIEN à personne : l'ancien code garde ses droits
-- d'écriture, le nouveau code trouve le registre et la colonne dont il a
-- besoin. Elle s'applique donc AVANT le déploiement, sans aucune fenêtre de
-- dégradation.
-- La 0076 retire les droits d'écriture au client : elle s'applique APRÈS que
-- le nouveau code soit en vol (lui écrit en service-role, donc elle ne le
-- gêne pas). Appliquée trop tôt, elle priverait l'ANCIEN code du droit
-- d'écrire — réglage de cadençage et rattachement en erreur le temps du
-- déploiement.
--
-- Idempotente (IF NOT EXISTS / DROP IF EXISTS).

-- (b) Journal permanent : quel compte Unipile appartient à qui.
-- PAS de clé étrangère vers auth.users, volontairement : ce journal est un
-- registre de sécurité, il doit SURVIVRE à la suppression d'un compte. Avec un
-- `on delete cascade`, supprimer un utilisateur rendrait son compte LinkedIn
-- — toujours connecté chez Unipile — réattribuable à n'importe qui.
create table if not exists public.unipile_account_claims (
  unipile_account_id text primary key,
  user_id            uuid not null,
  claimed_at         timestamptz not null default now(),
  last_seen_at       timestamptz not null default now()
);

create index if not exists idx_unipile_account_claims_user
  on public.unipile_account_claims (user_id);

-- RLS ON, zéro policy : service-role uniquement (patron `prospect_cache`).
-- Un client ne doit ni lire (qui possède quoi) ni écrire (se déclarer
-- propriétaire) ce registre.
alter table public.unipile_account_claims enable row level security;

-- Reprise de l'existant : sans ce backfill, les comptes DÉJÀ connectés
-- n'auraient aucune revendication au premier démarrage du nouveau code — donc
-- passeraient pour « libres » et resteraient captables. C'est la ligne qui
-- ferme la faille pour les clients actuels.
insert into public.unipile_account_claims (unipile_account_id, user_id)
select unipile_account_id, user_id
  from public.linkedin_outreach_accounts
 where unipile_account_id is not null
on conflict (unipile_account_id) do nothing;

-- (c) Horodatage de la demande de connexion, posé par POST /me/linkedin/outreach/connect.
-- Le repli n'acceptera qu'un compte Unipile créé APRÈS cet instant : un compte
-- qui traînait avant que le client clique « Connecter » n'est jamais le sien.
alter table public.linkedin_outreach_accounts
  add column if not exists connect_requested_at timestamptz;

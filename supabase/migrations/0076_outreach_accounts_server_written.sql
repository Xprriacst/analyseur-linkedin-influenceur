-- 0076 — `linkedin_outreach_accounts` devient SERVEUR-ÉCRITE, CLIENT-LISIBLE
--
-- Deuxième moitié du correctif de la 0075 (audit sécurité 2026-09-09).
--
-- Ce que ça ferme : la 0043 accorde `insert/update/delete` à `authenticated`
-- et la 0048 n'a resserré que l'UPDATE, en laissant `unipile_account_id` dans
-- la liste des colonnes autorisées. Avec la clé anon (publique) et son propre
-- JWT, un client écrivait donc l'identifiant du compte LinkedIn d'un AUTRE
-- client sur sa ligne — une seule clé API Unipile servant tout le monde, cela
-- suffisait à lire sa messagerie et à envoyer en son nom. Les `insert`/`delete`
-- restés ouverts permettaient en prime de SUPPRIMER puis RECRÉER sa ligne, ce
-- qui remettait `frozen` à false et `warmup_started_at` à zéro : le gel
-- anti-restriction et le warm-up que la 0048 rendait « incontournables » se
-- levaient en deux requêtes.
--
-- ⚠️ À APPLIQUER APRÈS LE DÉPLOIEMENT DU CODE, pas avant. Le nouveau code écrit
-- cette table en service-role : ces revoke ne le gênent pas. L'ancien code, lui,
-- écrit avec le jeton du client — appliquer trop tôt lui retire ce droit et fait
-- échouer le réglage de cadençage et le rattachement pendant la fenêtre de
-- déploiement.
--
-- Vérifié : un REVOKE au niveau table retire AUSSI les droits colonne par colonne
-- posés par 0048/0052 (contrôlé sur une table jetable — l'ACL retombe à
-- `authenticated=r`). Le SELECT est conservé : l'app lit cette ligne à chaque
-- écran de prospection.
-- Idempotente.

revoke insert, update, delete, truncate on public.linkedin_outreach_accounts from authenticated;
revoke insert, update, delete, truncate on public.linkedin_outreach_accounts from anon;

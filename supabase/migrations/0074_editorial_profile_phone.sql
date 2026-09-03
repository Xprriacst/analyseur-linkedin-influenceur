-- Téléphone du client, demandé à l'onboarding (décision d'Alex du 2026-09-03 :
-- champ OBLIGATOIRE dans le tunnel).
--
-- ⚠️ Rien dans le produit ne compose ce numéro aujourd'hui : il sert à
-- rappeler les inscrits. C'est donc une donnée personnelle collectée pour un
-- usage humain, pas pour une fonctionnalité — l'écran le dit au visiteur
-- (« on ne t'enverra pas de pub, c'est pour t'accompagner au démarrage »).
--
-- Idempotente. Les grants de `user_editorial_profiles` sont au niveau table
-- (vérifié) : la colonne est automatiquement couverte pour `authenticated`.
alter table if exists public.user_editorial_profiles
  add column if not exists phone text;

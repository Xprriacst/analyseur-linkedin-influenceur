-- 0066 : avatar IA — mode Digital Twin (vidéo d'entraînement + consentement).
--
-- Le mode photo (0065) reste inchangé et par défaut. Le Digital Twin ajoute
-- un type d'avatar (`heygen_avatar_type`) et le suivi du consentement HeyGen
-- (page hébergée par eux, webcam, lien valable ~24h) : `heygen_avatar_status`
-- gagne deux valeurs supplémentaires côté app (pas de contrainte SQL dessus,
-- même patron que `heygen_avatar_status` déjà en texte libre côté 0065) :
-- 'pending_consent' (avatar créé chez HeyGen, en attente que le client
-- confirme le consentement) et 'consent_expired' (24h passées sans
-- confirmation — une nouvelle demande de lien est nécessaire).
--
-- Idempotente (`IF NOT EXISTS`), patron des colonnes zernio_*/heygen_* déjà
-- en place.

alter table public.user_editorial_profiles
  add column if not exists heygen_avatar_type text default 'photo',
  add column if not exists heygen_consent_url text,
  add column if not exists heygen_consent_expires_at timestamptz;

comment on column public.user_editorial_profiles.heygen_avatar_type is
  'Type d''avatar HeyGen : photo (sans consentement) | digital_twin (vidéo d''entraînement, consentement HeyGen requis).';
comment on column public.user_editorial_profiles.heygen_consent_url is
  'Lien hébergé par HeyGen où le client confirme son consentement (webcam) pour un avatar digital_twin. NULL une fois le consentement acquis ou l''avatar en mode photo.';
comment on column public.user_editorial_profiles.heygen_consent_expires_at is
  'Expiration du lien de consentement ci-dessus (~24h chez HeyGen). Passé ce délai, heygen_avatar_status bascule en consent_expired côté app et une nouvelle demande (POST /me/avatar/digital-twin/consent) est nécessaire.';

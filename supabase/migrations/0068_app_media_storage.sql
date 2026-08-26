-- Stockage durable des images applicatives (self-photos, bibliothèque, veille).
-- Les uploads présignés Zernio vivent en /temp/ et expirent si aucun post ne les
-- publie ; ce bucket public sert aux images que l'app doit relire à long terme.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
select
  'app-media',
  'app-media',
  true,
  10485760,
  array['image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/gif']
where not exists (
  select 1 from storage.buckets where id = 'app-media'
);

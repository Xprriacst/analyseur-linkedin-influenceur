-- ALE-109 : Cache global d'influenceur pour l'analyse incrémentale.
-- Tables partagées cross-user (pas de user_id, pas de RLS).
-- Écrites uniquement par le pipeline d'analyse (admin_client / service-role).
-- Permet de ne classifier (LLM) que les nouveaux posts au lieu de tout reprendre.

create table if not exists public.influencer_cache (
    id               uuid primary key default gen_random_uuid(),
    handle           text not null,
    platform         text not null default 'linkedin',
    name             text,
    headline         text,
    follower_count   int,
    profile_url      text,
    raw_profile      jsonb,
    synthesis        jsonb,
    last_analyzed_at timestamptz not null default now(),
    created_at       timestamptz not null default now(),
    constraint influencer_cache_handle_platform_unique unique (handle, platform)
);

create table if not exists public.cached_posts (
    id                   uuid primary key default gen_random_uuid(),
    influencer_cache_id  uuid not null
        references public.influencer_cache(id) on delete cascade,
    url                  text not null,
    text                 text,
    posted_at            timestamptz,
    format               text,
    likes                int not null default 0,
    comments             int not null default 0,
    reposts              int not null default 0,
    engagement           int not null default 0,
    length_chars         int not null default 0,
    length_words         int not null default 0,
    -- Classifications LLM (null = pas encore classifié)
    stage                text,
    hook_type            text,
    topic                text,
    angle                text,
    classified_at        timestamptz,
    first_seen_at        timestamptz not null default now(),
    constraint cached_posts_cache_url_unique unique (influencer_cache_id, url)
);

create index if not exists idx_cached_posts_cache_id
    on public.cached_posts (influencer_cache_id);
create index if not exists idx_cached_posts_posted_at
    on public.cached_posts (influencer_cache_id, posted_at desc nulls last);

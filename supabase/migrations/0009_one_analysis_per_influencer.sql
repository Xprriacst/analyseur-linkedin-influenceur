-- Une seule analyse courante par influenceur et par utilisateur.
-- Les anciennes lignes dupliquees sont supprimees apres avoir conserve la plus recente.

alter table public.analyses
  add column if not exists updated_at timestamptz not null default now();

with ranked as (
  select
    id,
    first_value(id) over (
      partition by user_id, influencer_id
      order by updated_at desc, created_at desc, id desc
    ) as keep_id,
    row_number() over (
      partition by user_id, influencer_id
      order by updated_at desc, created_at desc, id desc
    ) as rn
  from public.analyses
  where user_id is not null
    and influencer_id is not null
),
rewired_job_items as (
  update public.analysis_job_items item
  set
    analysis_id = ranked.keep_id,
    updated_at = now()
  from ranked
  where ranked.rn > 1
    and item.analysis_id = ranked.id
  returning item.id
)
delete from public.analyses analysis
using ranked
where ranked.rn > 1
  and analysis.id = ranked.id;

create unique index if not exists analyses_user_influencer_unique
  on public.analyses(user_id, influencer_id);

create index if not exists idx_analyses_user_updated
  on public.analyses(user_id, updated_at desc);

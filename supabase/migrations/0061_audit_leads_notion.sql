-- 0061_audit_leads_notion.sql
-- Lien Notion (audit complet) + jeton pour une page publique miroir sur le site.
-- Idempotente.

alter table public.audit_leads
  add column if not exists notion_url text,
  add column if not exists notion_page_id text,
  add column if not exists public_token text;

create unique index if not exists audit_leads_public_token_uidx
  on public.audit_leads (public_token)
  where public_token is not null;

create index if not exists audit_leads_notion_page_id_idx
  on public.audit_leads (notion_page_id)
  where notion_page_id is not null;

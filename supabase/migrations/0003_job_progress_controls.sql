-- Diagnostic et contrôle des séries d'analyses.
-- À exécuter dans le SQL editor du projet Supabase zcxaxwqkswuefzlzpgvi.
--
-- Ajoute les champs nécessaires pour afficher la dernière étape connue,
-- détecter les jobs bloqués et permettre l'annulation/reprise.

alter table public.analysis_jobs
  add column if not exists current_step text,
  add column if not exists last_heartbeat_at timestamptz,
  add column if not exists error_code text,
  add column if not exists error_message text,
  add column if not exists cancel_requested_at timestamptz,
  add column if not exists cancelled_at timestamptz;

alter table public.analysis_job_items
  add column if not exists current_step text,
  add column if not exists last_heartbeat_at timestamptz,
  add column if not exists error_code text,
  add column if not exists error_message text,
  add column if not exists cancel_requested_at timestamptz,
  add column if not exists cancelled_at timestamptz;

-- Normalise les anciennes valeurs pour le nouveau vocabulaire UI.
update public.analysis_jobs
set status = case status
  when 'done' then 'completed'
  when 'error' then 'failed'
  else status
end
where status in ('done', 'error');

update public.analysis_job_items
set status = case status
  when 'pending' then 'queued'
  when 'done' then 'completed'
  when 'error' then 'failed'
  else status
end
where status in ('pending', 'done', 'error');

update public.analysis_jobs
set
  current_step = coalesce(current_step, case
    when status = 'completed' then 'Série terminée'
    when status = 'failed' then 'Série échouée'
    else 'En attente'
  end),
  last_heartbeat_at = coalesce(last_heartbeat_at, updated_at);

update public.analysis_job_items
set
  current_step = coalesce(current_step, case
    when status = 'completed' then 'Analyse terminée'
    when status = 'failed' then coalesce(error, 'Analyse échouée')
    else 'En attente'
  end),
  error_message = coalesce(error_message, error),
  last_heartbeat_at = coalesce(last_heartbeat_at, updated_at);

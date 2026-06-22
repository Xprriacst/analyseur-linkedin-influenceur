import type { SupabaseClient } from "@supabase/supabase-js";

// ── Types ────────────────────────────────────────────────────────────────────

export interface Company {
  id: string;
  user_id: string;
  name: string;
  domain: string | null;
  industry: string | null;
  headcount_range: string | null;
  hq_location: string | null;
  linkedin_company_url: string | null;
  status: "prospect" | "contacted" | "qualified" | "disqualified";
  notes: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Lead {
  id: string;
  user_id: string;
  company_id: string | null;
  full_name: string;
  job_title: string | null;
  linkedin_profile_url: string | null;
  email: string | null;
  status: "new" | "contacted" | "replied" | "meeting" | "qualified" | "disqualified";
  notes: string | null;
  metadata: Record<string, unknown>;
  engaged_post_urls: string[];
  created_at: string;
  updated_at: string;
}

export interface StrategySettings {
  id: string;
  user_id: string;
  tone: string | null;
  target_audience: string | null;
  value_proposition: string | null;
  message_template_1: string | null;
  message_template_2: string | null;
  auto_outreach_enabled: boolean;
  created_at: string;
  updated_at: string;
}

// ── Company CRUD ─────────────────────────────────────────────────────────────

export async function listCompanies(supabase: SupabaseClient): Promise<Company[]> {
  const { data, error } = await supabase
    .from("companies")
    .select("*")
    .order("created_at", { ascending: false });
  if (error) throw error;
  return (data ?? []) as Company[];
}

export async function createCompany(
  supabase: SupabaseClient,
  data: Omit<Company, "id" | "user_id" | "created_at" | "updated_at">
): Promise<Company> {
  const { data: row, error } = await supabase
    .from("companies")
    .insert(data)
    .select()
    .single();
  if (error) throw error;
  return row as Company;
}

export async function updateCompany(
  supabase: SupabaseClient,
  id: string,
  data: Partial<Omit<Company, "id" | "user_id" | "created_at" | "updated_at">>
): Promise<Company> {
  const { data: row, error } = await supabase
    .from("companies")
    .update({ ...data, updated_at: new Date().toISOString() })
    .eq("id", id)
    .select()
    .single();
  if (error) throw error;
  return row as Company;
}

export async function deleteCompany(supabase: SupabaseClient, id: string): Promise<void> {
  const { error } = await supabase.from("companies").delete().eq("id", id);
  if (error) throw error;
}

// ── Lead CRUD ────────────────────────────────────────────────────────────────

export async function listLeads(supabase: SupabaseClient): Promise<Lead[]> {
  const { data, error } = await supabase
    .from("leads")
    .select("*")
    .order("created_at", { ascending: false });
  if (error) throw error;
  return (data ?? []) as Lead[];
}

export async function createLead(
  supabase: SupabaseClient,
  data: Omit<Lead, "id" | "user_id" | "created_at" | "updated_at">
): Promise<Lead> {
  const { data: row, error } = await supabase
    .from("leads")
    .insert(data)
    .select()
    .single();
  if (error) throw error;
  return row as Lead;
}

export async function updateLead(
  supabase: SupabaseClient,
  id: string,
  data: Partial<Omit<Lead, "id" | "user_id" | "created_at" | "updated_at">>
): Promise<Lead> {
  const { data: row, error } = await supabase
    .from("leads")
    .update({ ...data, updated_at: new Date().toISOString() })
    .eq("id", id)
    .select()
    .single();
  if (error) throw error;
  return row as Lead;
}

export async function deleteLead(supabase: SupabaseClient, id: string): Promise<void> {
  const { error } = await supabase.from("leads").delete().eq("id", id);
  if (error) throw error;
}

// ── Strategy Settings ────────────────────────────────────────────────────────

export async function getStrategySettings(
  supabase: SupabaseClient
): Promise<StrategySettings | null> {
  const { data, error } = await supabase
    .from("strategy_settings")
    .select("*")
    .single();
  if (error && error.code !== "PGRST116") throw error; // PGRST116 = no rows
  return (data ?? null) as StrategySettings | null;
}

export async function upsertStrategySettings(
  supabase: SupabaseClient,
  data: Partial<
    Omit<StrategySettings, "id" | "user_id" | "created_at" | "updated_at">
  >
): Promise<StrategySettings> {
  const { data: row, error } = await supabase
    .from("strategy_settings")
    .upsert({ ...data, updated_at: new Date().toISOString() }, { onConflict: "user_id" })
    .select()
    .single();
  if (error) throw error;
  return row as StrategySettings;
}

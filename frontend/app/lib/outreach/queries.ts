import { supabase } from "../supabase";

type JsonRecord = Record<string, unknown>;
type DbRow = Record<string, any>;

export type LeadStatus = "new" | "qualified" | "contacted" | "replied" | "converted" | "archived";

export type UiCompany = {
  id: string;
  name: string;
  domain: string | null;
  websiteUrl: string | null;
  linkedinUrl: string | null;
  industry: string | null;
  companySize: string | null;
  location: string | null;
  description: string | null;
  rawData: JsonRecord;
  createdAt: string;
  updatedAt: string;
};

export type UiLead = {
  id: string;
  companyId: string | null;
  monitoredKeywordId: string | null;
  sourcePostId: string | null;
  firstName: string | null;
  lastName: string | null;
  fullName: string;
  title: string | null;
  linkedinUrl: string | null;
  email: string | null;
  phone: string | null;
  companyName: string | null;
  sourceUrl: string | null;
  engagementType: string | null;
  score: number;
  status: LeadStatus;
  signal: JsonRecord;
  rawData: JsonRecord;
  createdAt: string;
  updatedAt: string;
  company: UiCompany | null;
};

export type LeadInput = {
  companyId?: string | null;
  monitoredKeywordId?: string | null;
  sourcePostId?: string | null;
  firstName?: string | null;
  lastName?: string | null;
  fullName: string;
  title?: string | null;
  linkedinUrl?: string | null;
  email?: string | null;
  phone?: string | null;
  companyName?: string | null;
  sourceUrl?: string | null;
  engagementType?: string | null;
  score?: number;
  status?: LeadStatus;
  signal?: JsonRecord;
  rawData?: JsonRecord;
};

export type CompanyInput = {
  name: string;
  domain?: string | null;
  websiteUrl?: string | null;
  linkedinUrl?: string | null;
  industry?: string | null;
  companySize?: string | null;
  location?: string | null;
  description?: string | null;
  rawData?: JsonRecord;
};

export type ListLeadsOptions = {
  status?: LeadStatus;
  monitoredKeywordId?: string;
  sourcePostId?: string;
  limit?: number;
};

export type StrategySettings = {
  id: string;
  targetTitles: string[];
  targetIndustries: string[];
  targetCompanySizes: string[];
  targetLocations: string[];
  signals: string[];
  tone: string | null;
  neverDo: string[];
  weeklyVolume: number;
  createdAt: string;
  updatedAt: string;
};

export type StrategySettingsInput = {
  targetTitles?: string[];
  targetIndustries?: string[];
  targetCompanySizes?: string[];
  targetLocations?: string[];
  signals?: string[];
  tone?: string | null;
  neverDo?: string[];
  weeklyVolume?: number;
};

function asRecord(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as JsonRecord) : {};
}

function toCompany(row: DbRow | null | undefined): UiCompany | null {
  if (!row) return null;
  return {
    id: String(row.id),
    name: String(row.name || ""),
    domain: row.domain ?? null,
    websiteUrl: row.website_url ?? null,
    linkedinUrl: row.linkedin_url ?? null,
    industry: row.industry ?? null,
    companySize: row.company_size ?? null,
    location: row.location ?? null,
    description: row.description ?? null,
    rawData: asRecord(row.raw_data),
    createdAt: String(row.created_at || ""),
    updatedAt: String(row.updated_at || ""),
  };
}

export function toUiLead(row: DbRow): UiLead {
  return {
    id: String(row.id),
    companyId: row.company_id ?? null,
    monitoredKeywordId: row.monitored_keyword_id ?? null,
    sourcePostId: row.source_post_id ?? null,
    firstName: row.first_name ?? null,
    lastName: row.last_name ?? null,
    fullName: String(row.full_name || ""),
    title: row.title ?? null,
    linkedinUrl: row.linkedin_url ?? null,
    email: row.email ?? null,
    phone: row.phone ?? null,
    companyName: row.company_name ?? null,
    sourceUrl: row.source_url ?? null,
    engagementType: row.engagement_type ?? null,
    score: Number(row.score ?? 0),
    status: (row.status || "new") as LeadStatus,
    signal: asRecord(row.signal),
    rawData: asRecord(row.raw_data),
    createdAt: String(row.created_at || ""),
    updatedAt: String(row.updated_at || ""),
    company: toCompany(row.companies),
  };
}

function companyInputToRow(input: CompanyInput): DbRow {
  return {
    name: input.name,
    domain: input.domain ?? null,
    website_url: input.websiteUrl ?? null,
    linkedin_url: input.linkedinUrl ?? null,
    industry: input.industry ?? null,
    company_size: input.companySize ?? null,
    location: input.location ?? null,
    description: input.description ?? null,
    raw_data: input.rawData ?? {},
    updated_at: new Date().toISOString(),
  };
}

function leadInputToRow(input: Partial<LeadInput>): DbRow {
  const row: DbRow = {};
  if ("companyId" in input) row.company_id = input.companyId ?? null;
  if ("monitoredKeywordId" in input) row.monitored_keyword_id = input.monitoredKeywordId ?? null;
  if ("sourcePostId" in input) row.source_post_id = input.sourcePostId ?? null;
  if ("firstName" in input) row.first_name = input.firstName ?? null;
  if ("lastName" in input) row.last_name = input.lastName ?? null;
  if ("fullName" in input) row.full_name = input.fullName;
  if ("title" in input) row.title = input.title ?? null;
  if ("linkedinUrl" in input) row.linkedin_url = input.linkedinUrl ?? null;
  if ("email" in input) row.email = input.email ?? null;
  if ("phone" in input) row.phone = input.phone ?? null;
  if ("companyName" in input) row.company_name = input.companyName ?? null;
  if ("sourceUrl" in input) row.source_url = input.sourceUrl ?? null;
  if ("engagementType" in input) row.engagement_type = input.engagementType ?? null;
  if ("score" in input) row.score = input.score ?? 0;
  if ("status" in input) row.status = input.status ?? "new";
  if ("signal" in input) row.signal = input.signal ?? {};
  if ("rawData" in input) row.raw_data = input.rawData ?? {};
  row.updated_at = new Date().toISOString();
  return row;
}

export async function listCompanies(): Promise<UiCompany[]> {
  const { data, error } = await supabase
    .from("companies")
    .select("*")
    .order("created_at", { ascending: false });

  if (error) throw error;
  return (data ?? []).map((row) => toCompany(row)).filter((row): row is UiCompany => !!row);
}

export async function createCompany(input: CompanyInput): Promise<UiCompany> {
  const { data, error } = await supabase
    .from("companies")
    .insert(companyInputToRow(input))
    .select("*")
    .single();

  if (error) throw error;
  const company = toCompany(data);
  if (!company) throw new Error("Company creation returned no data.");
  return company;
}

export async function listLeads(options: ListLeadsOptions = {}): Promise<UiLead[]> {
  let query = supabase
    .from("leads")
    .select("*, companies(*)")
    .order("created_at", { ascending: false });

  if (options.status) query = query.eq("status", options.status);
  if (options.monitoredKeywordId) query = query.eq("monitored_keyword_id", options.monitoredKeywordId);
  if (options.sourcePostId) query = query.eq("source_post_id", options.sourcePostId);
  if (options.limit) query = query.limit(options.limit);

  const { data, error } = await query;
  if (error) throw error;
  return (data ?? []).map(toUiLead);
}

export async function getLead(id: string): Promise<UiLead | null> {
  const { data, error } = await supabase
    .from("leads")
    .select("*, companies(*)")
    .eq("id", id)
    .maybeSingle();

  if (error) throw error;
  return data ? toUiLead(data) : null;
}

export async function createLead(input: LeadInput): Promise<UiLead> {
  const { data, error } = await supabase
    .from("leads")
    .insert(leadInputToRow(input))
    .select("*, companies(*)")
    .single();

  if (error) throw error;
  return toUiLead(data);
}

export async function updateLead(id: string, patch: Partial<LeadInput>): Promise<UiLead> {
  const { data, error } = await supabase
    .from("leads")
    .update(leadInputToRow(patch))
    .eq("id", id)
    .select("*, companies(*)")
    .single();

  if (error) throw error;
  return toUiLead(data);
}

export async function deleteLead(id: string): Promise<void> {
  const { error } = await supabase.from("leads").delete().eq("id", id);
  if (error) throw error;
}

export function toStrategySettings(row: DbRow): StrategySettings {
  return {
    id: String(row.id),
    targetTitles: row.target_titles ?? [],
    targetIndustries: row.target_industries ?? [],
    targetCompanySizes: row.target_company_sizes ?? [],
    targetLocations: row.target_locations ?? [],
    signals: row.signals ?? [],
    tone: row.tone ?? null,
    neverDo: row.never_do ?? [],
    weeklyVolume: Number(row.weekly_volume ?? 0),
    createdAt: String(row.created_at || ""),
    updatedAt: String(row.updated_at || ""),
  };
}

function strategySettingsInputToRow(input: StrategySettingsInput): DbRow {
  const row: DbRow = { updated_at: new Date().toISOString() };
  if ("targetTitles" in input) row.target_titles = input.targetTitles ?? [];
  if ("targetIndustries" in input) row.target_industries = input.targetIndustries ?? [];
  if ("targetCompanySizes" in input) row.target_company_sizes = input.targetCompanySizes ?? [];
  if ("targetLocations" in input) row.target_locations = input.targetLocations ?? [];
  if ("signals" in input) row.signals = input.signals ?? [];
  if ("tone" in input) row.tone = input.tone ?? null;
  if ("neverDo" in input) row.never_do = input.neverDo ?? [];
  if ("weeklyVolume" in input) row.weekly_volume = input.weeklyVolume ?? 0;
  return row;
}

export async function getStrategySettings(): Promise<StrategySettings | null> {
  const { data, error } = await supabase
    .from("strategy_settings")
    .select("*")
    .maybeSingle();

  if (error) throw error;
  return data ? toStrategySettings(data) : null;
}

export async function upsertStrategySettings(input: StrategySettingsInput): Promise<StrategySettings> {
  const { data: authData, error: authError } = await supabase.auth.getUser();
  if (authError) throw authError;
  const userId = authData.user?.id;
  if (!userId) throw new Error("Authentication required to save outreach strategy.");

  const { data, error } = await supabase
    .from("strategy_settings")
    .upsert({ user_id: userId, ...strategySettingsInputToRow(input) }, { onConflict: "user_id" })
    .select("*")
    .single();

  if (error) throw error;
  return toStrategySettings(data);
}

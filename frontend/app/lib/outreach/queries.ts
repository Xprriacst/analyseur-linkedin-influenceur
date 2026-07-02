import { supabase } from "../supabase";

export type LeadStatus =
  | "new"
  | "qualified"
  | "contacted"
  | "replied"
  | "converted"
  | "archived";

export interface UiCompany {
  id: string;
  userId: string;
  name: string;
  domain: string | null;
  websiteUrl: string | null;
  linkedinUrl: string | null;
  industry: string | null;
  companySize: string | null;
  location: string | null;
  description: string | null;
  rawData: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface UiLead {
  id: string;
  userId: string;
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
  signal: Record<string, unknown>;
  rawData: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface CompanyInput {
  name: string;
  domain?: string | null;
  websiteUrl?: string | null;
  linkedinUrl?: string | null;
  industry?: string | null;
  companySize?: string | null;
  location?: string | null;
  description?: string | null;
  rawData?: Record<string, unknown>;
}

export interface LeadInput {
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
  signal?: Record<string, unknown>;
  rawData?: Record<string, unknown>;
}

export interface ListLeadsOptions {
  status?: LeadStatus;
  monitoredKeywordId?: string;
  sourcePostId?: string;
  limit?: number;
}

export interface StrategySettings {
  id: string;
  userId: string;
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
}

export interface StrategySettingsInput {
  targetTitles?: string[];
  targetIndustries?: string[];
  targetCompanySizes?: string[];
  targetLocations?: string[];
  signals?: string[];
  tone?: string | null;
  neverDo?: string[];
  weeklyVolume?: number;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function toUiLeadFromRealtime(row: any): UiLead {
  return toUiLead(row);
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function toUiLead(row: any): UiLead {
  return {
    id: row.id,
    userId: row.user_id,
    companyId: row.company_id ?? null,
    monitoredKeywordId: row.monitored_keyword_id ?? null,
    sourcePostId: row.source_post_id ?? null,
    firstName: row.first_name ?? null,
    lastName: row.last_name ?? null,
    fullName: row.full_name,
    title: row.title ?? null,
    linkedinUrl: row.linkedin_url ?? null,
    email: row.email ?? null,
    phone: row.phone ?? null,
    companyName: row.company_name ?? null,
    sourceUrl: row.source_url ?? null,
    engagementType: row.engagement_type ?? null,
    score: row.score,
    status: row.status as LeadStatus,
    signal: row.signal ?? {},
    rawData: row.raw_data ?? {},
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function toCompany(row: any): UiCompany {
  return {
    id: row.id,
    userId: row.user_id,
    name: row.name,
    domain: row.domain ?? null,
    websiteUrl: row.website_url ?? null,
    linkedinUrl: row.linkedin_url ?? null,
    industry: row.industry ?? null,
    companySize: row.company_size ?? null,
    location: row.location ?? null,
    description: row.description ?? null,
    rawData: row.raw_data ?? {},
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function toStrategySettings(row: any): StrategySettings {
  return {
    id: row.id,
    userId: row.user_id,
    targetTitles: row.target_titles ?? [],
    targetIndustries: row.target_industries ?? [],
    targetCompanySizes: row.target_company_sizes ?? [],
    targetLocations: row.target_locations ?? [],
    signals: row.signals ?? [],
    tone: row.tone ?? null,
    neverDo: row.never_do ?? [],
    weeklyVolume: row.weekly_volume,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

function companyInputToRow(input: CompanyInput) {
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
  };
}

function leadInputToRow(input: LeadInput) {
  return {
    company_id: input.companyId ?? null,
    monitored_keyword_id: input.monitoredKeywordId ?? null,
    source_post_id: input.sourcePostId ?? null,
    first_name: input.firstName ?? null,
    last_name: input.lastName ?? null,
    full_name: input.fullName,
    title: input.title ?? null,
    linkedin_url: input.linkedinUrl ?? null,
    email: input.email ?? null,
    phone: input.phone ?? null,
    company_name: input.companyName ?? null,
    source_url: input.sourceUrl ?? null,
    engagement_type: input.engagementType ?? null,
    score: input.score ?? 0,
    status: input.status ?? "new",
    signal: input.signal ?? {},
    raw_data: input.rawData ?? {},
  };
}

function strategySettingsInputToRow(input: StrategySettingsInput) {
  return {
    target_titles: input.targetTitles ?? [],
    target_industries: input.targetIndustries ?? [],
    target_company_sizes: input.targetCompanySizes ?? [],
    target_locations: input.targetLocations ?? [],
    signals: input.signals ?? [],
    tone: input.tone ?? null,
    never_do: input.neverDo ?? [],
    weekly_volume: input.weeklyVolume ?? 0,
    updated_at: new Date().toISOString(),
  };
}

export async function listCompanies(): Promise<UiCompany[]> {
  const { data, error } = await supabase
    .from("companies")
    .select("*")
    .order("created_at", { ascending: false });
  if (error) throw error;
  return (data ?? []).map(toCompany);
}

export async function createCompany(input: CompanyInput): Promise<UiCompany> {
  const { data, error } = await supabase
    .from("companies")
    .insert(companyInputToRow(input))
    .select()
    .single();
  if (error) throw error;
  return toCompany(data);
}

export async function listLeads(options: ListLeadsOptions = {}): Promise<UiLead[]> {
  let query = supabase
    .from("leads")
    .select("*")
    .order("created_at", { ascending: false });

  if (options.status) query = query.eq("status", options.status);
  if (options.monitoredKeywordId)
    query = query.eq("monitored_keyword_id", options.monitoredKeywordId);
  if (options.sourcePostId)
    query = query.eq("source_post_id", options.sourcePostId);
  if (options.limit) query = query.limit(options.limit);

  const { data, error } = await query;
  if (error) throw error;
  return (data ?? []).map(toUiLead);
}

export async function getLead(id: string): Promise<UiLead> {
  const { data, error } = await supabase
    .from("leads")
    .select("*")
    .eq("id", id)
    .single();
  if (error) throw error;
  return toUiLead(data);
}

export async function createLead(input: LeadInput): Promise<UiLead> {
  const { data, error } = await supabase
    .from("leads")
    .insert(leadInputToRow(input))
    .select()
    .single();
  if (error) throw error;
  return toUiLead(data);
}

export async function updateLead(
  id: string,
  input: Partial<LeadInput>
): Promise<UiLead> {
  const row: Record<string, unknown> = {};
  if (input.companyId !== undefined) row.company_id = input.companyId;
  if (input.monitoredKeywordId !== undefined)
    row.monitored_keyword_id = input.monitoredKeywordId;
  if (input.sourcePostId !== undefined) row.source_post_id = input.sourcePostId;
  if (input.firstName !== undefined) row.first_name = input.firstName;
  if (input.lastName !== undefined) row.last_name = input.lastName;
  if (input.fullName !== undefined) row.full_name = input.fullName;
  if (input.title !== undefined) row.title = input.title;
  if (input.linkedinUrl !== undefined) row.linkedin_url = input.linkedinUrl;
  if (input.email !== undefined) row.email = input.email;
  if (input.phone !== undefined) row.phone = input.phone;
  if (input.companyName !== undefined) row.company_name = input.companyName;
  if (input.sourceUrl !== undefined) row.source_url = input.sourceUrl;
  if (input.engagementType !== undefined)
    row.engagement_type = input.engagementType;
  if (input.score !== undefined) row.score = input.score;
  if (input.status !== undefined) row.status = input.status;
  if (input.signal !== undefined) row.signal = input.signal;
  if (input.rawData !== undefined) row.raw_data = input.rawData;
  row.updated_at = new Date().toISOString();

  const { data, error } = await supabase
    .from("leads")
    .update(row)
    .eq("id", id)
    .select()
    .single();
  if (error) throw error;
  return toUiLead(data);
}

export async function deleteLead(id: string): Promise<void> {
  const { error } = await supabase.from("leads").delete().eq("id", id);
  if (error) throw error;
}

export async function getStrategySettings(): Promise<StrategySettings | null> {
  const { data, error } = await supabase
    .from("strategy_settings")
    .select("*")
    .maybeSingle();
  if (error) throw error;
  return data ? toStrategySettings(data) : null;
}

export async function upsertStrategySettings(
  input: StrategySettingsInput
): Promise<StrategySettings> {
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) throw new Error("Not authenticated");

  const { data, error } = await supabase
    .from("strategy_settings")
    .upsert(
      { user_id: user.id, ...strategySettingsInputToRow(input) },
      { onConflict: "user_id" }
    )
    .select()
    .single();
  if (error) throw error;
  return toStrategySettings(data);
}

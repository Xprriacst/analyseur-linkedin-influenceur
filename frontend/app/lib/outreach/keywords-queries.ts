import { supabase } from "../supabase";

type JsonRecord = Record<string, unknown>;
type DbRow = Record<string, any>;

export type UiMonitoredKeyword = {
  id: string;
  keyword: string;
  enabled: boolean;
  lastCheckedAt: string | null;
  createdAt: string;
  updatedAt: string;
};

export type UiMonitoredPost = {
  id: string;
  monitoredKeywordId: string | null;
  linkedinPostId: string | null;
  postUrl: string;
  authorName: string | null;
  authorUrl: string | null;
  content: string | null;
  publishedAt: string | null;
  reactionsCount: number;
  commentsCount: number;
  repostsCount: number;
  rawData: JsonRecord;
  createdAt: string;
  updatedAt: string;
};

export type MonitoredKeywordInput = {
  keyword: string;
  enabled?: boolean;
  lastCheckedAt?: string | null;
};

export type MonitoredPostInput = {
  monitoredKeywordId?: string | null;
  linkedinPostId?: string | null;
  postUrl: string;
  authorName?: string | null;
  authorUrl?: string | null;
  content?: string | null;
  publishedAt?: string | null;
  reactionsCount?: number;
  commentsCount?: number;
  repostsCount?: number;
  rawData?: JsonRecord;
};

function asRecord(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as JsonRecord) : {};
}

export function toUiMonitoredKeyword(row: DbRow): UiMonitoredKeyword {
  return {
    id: String(row.id),
    keyword: String(row.keyword || ""),
    enabled: Boolean(row.enabled),
    lastCheckedAt: row.last_checked_at ?? null,
    createdAt: String(row.created_at || ""),
    updatedAt: String(row.updated_at || ""),
  };
}

export function toUiMonitoredPost(row: DbRow): UiMonitoredPost {
  return {
    id: String(row.id),
    monitoredKeywordId: row.monitored_keyword_id ?? null,
    linkedinPostId: row.linkedin_post_id ?? null,
    postUrl: String(row.post_url || ""),
    authorName: row.author_name ?? null,
    authorUrl: row.author_url ?? null,
    content: row.content ?? null,
    publishedAt: row.published_at ?? null,
    reactionsCount: Number(row.reactions_count ?? 0),
    commentsCount: Number(row.comments_count ?? 0),
    repostsCount: Number(row.reposts_count ?? 0),
    rawData: asRecord(row.raw_data),
    createdAt: String(row.created_at || ""),
    updatedAt: String(row.updated_at || ""),
  };
}

function keywordInputToRow(input: Partial<MonitoredKeywordInput>): DbRow {
  const row: DbRow = { updated_at: new Date().toISOString() };
  if ("keyword" in input) row.keyword = input.keyword;
  if ("enabled" in input) row.enabled = input.enabled ?? true;
  if ("lastCheckedAt" in input) row.last_checked_at = input.lastCheckedAt ?? null;
  return row;
}

function postInputToRow(input: Partial<MonitoredPostInput>): DbRow {
  const row: DbRow = { updated_at: new Date().toISOString() };
  if ("monitoredKeywordId" in input) row.monitored_keyword_id = input.monitoredKeywordId ?? null;
  if ("linkedinPostId" in input) row.linkedin_post_id = input.linkedinPostId ?? null;
  if ("postUrl" in input) row.post_url = input.postUrl;
  if ("authorName" in input) row.author_name = input.authorName ?? null;
  if ("authorUrl" in input) row.author_url = input.authorUrl ?? null;
  if ("content" in input) row.content = input.content ?? null;
  if ("publishedAt" in input) row.published_at = input.publishedAt ?? null;
  if ("reactionsCount" in input) row.reactions_count = input.reactionsCount ?? 0;
  if ("commentsCount" in input) row.comments_count = input.commentsCount ?? 0;
  if ("repostsCount" in input) row.reposts_count = input.repostsCount ?? 0;
  if ("rawData" in input) row.raw_data = input.rawData ?? {};
  return row;
}

export async function listMonitoredKeywords(): Promise<UiMonitoredKeyword[]> {
  const { data, error } = await supabase
    .from("monitored_keywords")
    .select("*")
    .order("created_at", { ascending: false });

  if (error) throw error;
  return (data ?? []).map(toUiMonitoredKeyword);
}

export async function createMonitoredKeyword(input: MonitoredKeywordInput): Promise<UiMonitoredKeyword> {
  const { data, error } = await supabase
    .from("monitored_keywords")
    .insert(keywordInputToRow(input))
    .select("*")
    .single();

  if (error) throw error;
  return toUiMonitoredKeyword(data);
}

export async function updateMonitoredKeyword(
  id: string,
  patch: Partial<MonitoredKeywordInput>,
): Promise<UiMonitoredKeyword> {
  const { data, error } = await supabase
    .from("monitored_keywords")
    .update(keywordInputToRow(patch))
    .eq("id", id)
    .select("*")
    .single();

  if (error) throw error;
  return toUiMonitoredKeyword(data);
}

export async function deleteMonitoredKeyword(id: string): Promise<void> {
  const { error } = await supabase.from("monitored_keywords").delete().eq("id", id);
  if (error) throw error;
}

export async function listMonitoredPosts(monitoredKeywordId?: string): Promise<UiMonitoredPost[]> {
  let query = supabase
    .from("monitored_posts")
    .select("*")
    .order("created_at", { ascending: false });

  if (monitoredKeywordId) query = query.eq("monitored_keyword_id", monitoredKeywordId);

  const { data, error } = await query;
  if (error) throw error;
  return (data ?? []).map(toUiMonitoredPost);
}

export async function createMonitoredPost(input: MonitoredPostInput): Promise<UiMonitoredPost> {
  const { data, error } = await supabase
    .from("monitored_posts")
    .insert(postInputToRow(input))
    .select("*")
    .single();

  if (error) throw error;
  return toUiMonitoredPost(data);
}

export async function updateMonitoredPost(
  id: string,
  patch: Partial<MonitoredPostInput>,
): Promise<UiMonitoredPost> {
  const { data, error } = await supabase
    .from("monitored_posts")
    .update(postInputToRow(patch))
    .eq("id", id)
    .select("*")
    .single();

  if (error) throw error;
  return toUiMonitoredPost(data);
}

export async function deleteMonitoredPost(id: string): Promise<void> {
  const { error } = await supabase.from("monitored_posts").delete().eq("id", id);
  if (error) throw error;
}

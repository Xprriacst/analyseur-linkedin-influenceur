import { supabase } from "../supabase";

export interface UiMonitoredKeyword {
  id: string;
  userId: string;
  keyword: string;
  enabled: boolean;
  lastCheckedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface UiMonitoredPost {
  id: string;
  userId: string;
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
  rawData: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface MonitoredKeywordInput {
  keyword: string;
  enabled?: boolean;
}

export interface MonitoredPostInput {
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
  rawData?: Record<string, unknown>;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function toUiMonitoredKeyword(row: any): UiMonitoredKeyword {
  return {
    id: row.id,
    userId: row.user_id,
    keyword: row.keyword,
    enabled: row.enabled,
    lastCheckedAt: row.last_checked_at ?? null,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function toUiMonitoredPost(row: any): UiMonitoredPost {
  return {
    id: row.id,
    userId: row.user_id,
    monitoredKeywordId: row.monitored_keyword_id ?? null,
    linkedinPostId: row.linkedin_post_id ?? null,
    postUrl: row.post_url,
    authorName: row.author_name ?? null,
    authorUrl: row.author_url ?? null,
    content: row.content ?? null,
    publishedAt: row.published_at ?? null,
    reactionsCount: row.reactions_count ?? 0,
    commentsCount: row.comments_count ?? 0,
    repostsCount: row.reposts_count ?? 0,
    rawData: row.raw_data ?? {},
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

function keywordInputToRow(input: MonitoredKeywordInput) {
  return {
    keyword: input.keyword,
    enabled: input.enabled ?? true,
  };
}

function postInputToRow(input: MonitoredPostInput) {
  return {
    monitored_keyword_id: input.monitoredKeywordId ?? null,
    linkedin_post_id: input.linkedinPostId ?? null,
    post_url: input.postUrl,
    author_name: input.authorName ?? null,
    author_url: input.authorUrl ?? null,
    content: input.content ?? null,
    published_at: input.publishedAt ?? null,
    reactions_count: input.reactionsCount ?? 0,
    comments_count: input.commentsCount ?? 0,
    reposts_count: input.repostsCount ?? 0,
    raw_data: input.rawData ?? {},
  };
}

export async function listMonitoredKeywords(): Promise<UiMonitoredKeyword[]> {
  const { data, error } = await supabase
    .from("monitored_keywords")
    .select("*")
    .order("created_at", { ascending: false });
  if (error) throw error;
  return (data ?? []).map(toUiMonitoredKeyword);
}

export async function createMonitoredKeyword(
  input: MonitoredKeywordInput
): Promise<UiMonitoredKeyword> {
  const { data, error } = await supabase
    .from("monitored_keywords")
    .insert(keywordInputToRow(input))
    .select()
    .single();
  if (error) throw error;
  return toUiMonitoredKeyword(data);
}

export async function updateMonitoredKeyword(
  id: string,
  input: Partial<MonitoredKeywordInput>
): Promise<UiMonitoredKeyword> {
  const row: Record<string, unknown> = { updated_at: new Date().toISOString() };
  if (input.keyword !== undefined) row.keyword = input.keyword;
  if (input.enabled !== undefined) row.enabled = input.enabled;

  const { data, error } = await supabase
    .from("monitored_keywords")
    .update(row)
    .eq("id", id)
    .select()
    .single();
  if (error) throw error;
  return toUiMonitoredKeyword(data);
}

export async function deleteMonitoredKeyword(id: string): Promise<void> {
  const { error } = await supabase
    .from("monitored_keywords")
    .delete()
    .eq("id", id);
  if (error) throw error;
}

export async function listMonitoredPosts(
  monitoredKeywordId?: string
): Promise<UiMonitoredPost[]> {
  let query = supabase
    .from("monitored_posts")
    .select("*")
    .order("created_at", { ascending: false });

  if (monitoredKeywordId) {
    query = query.eq("monitored_keyword_id", monitoredKeywordId);
  }

  const { data, error } = await query;
  if (error) throw error;
  return (data ?? []).map(toUiMonitoredPost);
}

export async function createMonitoredPost(
  input: MonitoredPostInput
): Promise<UiMonitoredPost> {
  const { data, error } = await supabase
    .from("monitored_posts")
    .insert(postInputToRow(input))
    .select()
    .single();
  if (error) throw error;
  return toUiMonitoredPost(data);
}

export async function updateMonitoredPost(
  id: string,
  input: Partial<MonitoredPostInput>
): Promise<UiMonitoredPost> {
  const row: Record<string, unknown> = { updated_at: new Date().toISOString() };
  if (input.monitoredKeywordId !== undefined)
    row.monitored_keyword_id = input.monitoredKeywordId;
  if (input.linkedinPostId !== undefined)
    row.linkedin_post_id = input.linkedinPostId;
  if (input.postUrl !== undefined) row.post_url = input.postUrl;
  if (input.authorName !== undefined) row.author_name = input.authorName;
  if (input.authorUrl !== undefined) row.author_url = input.authorUrl;
  if (input.content !== undefined) row.content = input.content;
  if (input.publishedAt !== undefined) row.published_at = input.publishedAt;
  if (input.reactionsCount !== undefined)
    row.reactions_count = input.reactionsCount;
  if (input.commentsCount !== undefined) row.comments_count = input.commentsCount;
  if (input.repostsCount !== undefined) row.reposts_count = input.repostsCount;
  if (input.rawData !== undefined) row.raw_data = input.rawData;

  const { data, error } = await supabase
    .from("monitored_posts")
    .update(row)
    .eq("id", id)
    .select()
    .single();
  if (error) throw error;
  return toUiMonitoredPost(data);
}

export async function deleteMonitoredPost(id: string): Promise<void> {
  const { error } = await supabase.from("monitored_posts").delete().eq("id", id);
  if (error) throw error;
}

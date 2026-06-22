import type { SupabaseClient } from "@supabase/supabase-js";

// ── Types ────────────────────────────────────────────────────────────────────

export interface MonitoredKeyword {
  id: string;
  user_id: string;
  keyword: string;
  description: string | null;
  status: "active" | "paused";
  match_count: number;
  last_run_at: string | null;
  created_at: string;
}

export interface MonitoredPost {
  id: string;
  keyword_id: string;
  author_linkedin_url: string | null;
  author_name: string | null;
  post_url: string;
  post_content: string | null;
  posted_at: string | null;
  likes_count: number;
  comments_count: number;
  relevance_score: number | null;
  processed: boolean;
  lead_id: string | null;
  created_at: string;
}

// ── Keyword CRUD ─────────────────────────────────────────────────────────────

export async function listKeywords(supabase: SupabaseClient): Promise<MonitoredKeyword[]> {
  const { data, error } = await supabase
    .from("monitored_keywords")
    .select("*")
    .order("created_at", { ascending: false });
  if (error) throw error;
  return (data ?? []) as MonitoredKeyword[];
}

export async function createKeyword(
  supabase: SupabaseClient,
  keyword: string,
  description?: string
): Promise<MonitoredKeyword> {
  const { data, error } = await supabase
    .from("monitored_keywords")
    .insert({ keyword, description: description ?? null })
    .select()
    .single();
  if (error) throw error;
  return data as MonitoredKeyword;
}

export async function updateKeywordStatus(
  supabase: SupabaseClient,
  id: string,
  status: "active" | "paused"
): Promise<MonitoredKeyword> {
  const { data, error } = await supabase
    .from("monitored_keywords")
    .update({ status })
    .eq("id", id)
    .select()
    .single();
  if (error) throw error;
  return data as MonitoredKeyword;
}

export async function deleteKeyword(supabase: SupabaseClient, id: string): Promise<void> {
  const { error } = await supabase.from("monitored_keywords").delete().eq("id", id);
  if (error) throw error;
}

// ── Monitored Posts ──────────────────────────────────────────────────────────

export async function listPostsForKeyword(
  supabase: SupabaseClient,
  keywordId: string
): Promise<MonitoredPost[]> {
  const { data, error } = await supabase
    .from("monitored_posts")
    .select("*")
    .eq("keyword_id", keywordId)
    .order("created_at", { ascending: false });
  if (error) throw error;
  return (data ?? []) as MonitoredPost[];
}

export async function markPostProcessed(
  supabase: SupabaseClient,
  postId: string,
  leadId?: string
): Promise<MonitoredPost> {
  const { data, error } = await supabase
    .from("monitored_posts")
    .update({ processed: true, lead_id: leadId ?? null })
    .eq("id", postId)
    .select()
    .single();
  if (error) throw error;
  return data as MonitoredPost;
}

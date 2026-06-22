"use client";

import { useEffect, useState } from "react";
import { createClient } from "@supabase/supabase-js";
import { Loader2, Plus, Trash2, ToggleLeft, ToggleRight, UserPlus, CheckCircle2 } from "lucide-react";
import {
  listKeywords,
  createKeyword,
  updateKeywordStatus,
  deleteKeyword,
  listPostsForKeyword,
  markPostProcessed,
  type MonitoredKeyword,
  type MonitoredPost,
} from "@/app/lib/outreach";
import { Button } from "@/app/components/ui/button";
import { Input } from "@/app/components/ui/input";
import { Badge } from "@/app/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/app/components/ui/card";

// ── Supabase client ───────────────────────────────────────────────────────────

const SUPABASE_URL =
  process.env.NEXT_PUBLIC_SUPABASE_URL ?? "https://zcxaxwqkswuefzlzpgvi.supabase.co";
const SUPABASE_ANON_KEY =
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ??
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpjeGF4d3Frc3d1ZWZ6bHpwZ3ZpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODEwMjU2NjIsImV4cCI6MjA5NjYwMTY2Mn0.AO5J-JdO0XYSvaRejq44cvnX1pC6qactw7X9O9-mS9U";

const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

// ── Helper ────────────────────────────────────────────────────────────────────

function truncate(text: string | null, maxLen = 160): string {
  if (!text) return "";
  return text.length > maxLen ? text.slice(0, maxLen) + "…" : text;
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function OutreachPage() {
  const [keywords, setKeywords] = useState<MonitoredKeyword[]>([]);
  const [loadingKeywords, setLoadingKeywords] = useState(true);

  const [selectedKeywordId, setSelectedKeywordId] = useState<string | null>(null);
  const [posts, setPosts] = useState<MonitoredPost[]>([]);
  const [loadingPosts, setLoadingPosts] = useState(false);

  const [newKeyword, setNewKeyword] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  const [actionLoading, setActionLoading] = useState<Record<string, boolean>>({});

  // Load keywords on mount
  useEffect(() => {
    loadKeywords();
  }, []);

  // Load posts when keyword selection changes
  useEffect(() => {
    if (!selectedKeywordId) {
      setPosts([]);
      return;
    }
    loadPosts(selectedKeywordId);
  }, [selectedKeywordId]);

  async function loadKeywords() {
    setLoadingKeywords(true);
    try {
      const data = await listKeywords(supabase);
      setKeywords(data);
      if (data.length > 0 && !selectedKeywordId) {
        setSelectedKeywordId(data[0].id);
      }
    } catch (err) {
      console.error("Failed to load keywords:", err);
    } finally {
      setLoadingKeywords(false);
    }
  }

  async function loadPosts(keywordId: string) {
    setLoadingPosts(true);
    try {
      const data = await listPostsForKeyword(supabase, keywordId);
      setPosts(data);
    } catch (err) {
      console.error("Failed to load posts:", err);
    } finally {
      setLoadingPosts(false);
    }
  }

  async function handleAddKeyword(e: React.FormEvent) {
    e.preventDefault();
    const kw = newKeyword.trim();
    if (!kw) return;
    setAdding(true);
    setAddError(null);
    try {
      const created = await createKeyword(supabase, kw, newDescription.trim() || undefined);
      setKeywords((prev) => [created, ...prev]);
      setNewKeyword("");
      setNewDescription("");
      setSelectedKeywordId(created.id);
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "Erreur lors de l'ajout");
    } finally {
      setAdding(false);
    }
  }

  async function handleToggleStatus(kw: MonitoredKeyword) {
    const newStatus = kw.status === "active" ? "paused" : "active";
    setActionLoading((prev) => ({ ...prev, [`toggle-${kw.id}`]: true }));
    try {
      const updated = await updateKeywordStatus(supabase, kw.id, newStatus);
      setKeywords((prev) => prev.map((k) => (k.id === kw.id ? updated : k)));
    } catch (err) {
      console.error("Failed to toggle status:", err);
    } finally {
      setActionLoading((prev) => ({ ...prev, [`toggle-${kw.id}`]: false }));
    }
  }

  async function handleDeleteKeyword(id: string) {
    if (!confirm("Supprimer ce mot-clé et tous ses posts détectés ?")) return;
    setActionLoading((prev) => ({ ...prev, [`delete-kw-${id}`]: true }));
    try {
      await deleteKeyword(supabase, id);
      setKeywords((prev) => prev.filter((k) => k.id !== id));
      if (selectedKeywordId === id) {
        const remaining = keywords.filter((k) => k.id !== id);
        setSelectedKeywordId(remaining.length > 0 ? remaining[0].id : null);
      }
    } catch (err) {
      console.error("Failed to delete keyword:", err);
    } finally {
      setActionLoading((prev) => ({ ...prev, [`delete-kw-${id}`]: false }));
    }
  }

  async function handleCreateLead(post: MonitoredPost) {
    setActionLoading((prev) => ({ ...prev, [`lead-${post.id}`]: true }));
    try {
      await markPostProcessed(supabase, post.id);
      setPosts((prev) =>
        prev.map((p) => (p.id === post.id ? { ...p, processed: true } : p))
      );
    } catch (err) {
      console.error("Failed to mark post processed:", err);
    } finally {
      setActionLoading((prev) => ({ ...prev, [`lead-${post.id}`]: false }));
    }
  }

  const selectedKeyword = keywords.find((k) => k.id === selectedKeywordId) ?? null;

  return (
    <div style={{ minHeight: "100vh", background: "var(--surface-low)", padding: "24px" }}>
      <div style={{ maxWidth: 1100, margin: "0 auto" }}>
        {/* Header */}
        <div style={{ marginBottom: 24 }}>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: "var(--ink)", margin: 0 }}>
            Engagement Hunter
          </h1>
          <p style={{ color: "var(--muted)", marginTop: 4, fontSize: 14 }}>
            Surveillez des mots-clés LinkedIn et identifiez des prospects parmi les commentateurs.
          </p>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: 20, alignItems: "start" }}>
          {/* Left column — Keywords */}
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {/* Add keyword form */}
            <Card>
              <CardHeader>
                <CardTitle style={{ fontSize: 15 }}>Ajouter un mot-clé</CardTitle>
                <CardDescription>Ex: "outil CRM", "prospection LinkedIn"</CardDescription>
              </CardHeader>
              <CardContent>
                <form onSubmit={handleAddKeyword} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <Input
                    placeholder="Mot-clé *"
                    value={newKeyword}
                    onChange={(e) => setNewKeyword(e.target.value)}
                    disabled={adding}
                    required
                  />
                  <Input
                    placeholder="Description (optionnel)"
                    value={newDescription}
                    onChange={(e) => setNewDescription(e.target.value)}
                    disabled={adding}
                  />
                  {addError && (
                    <p style={{ color: "var(--danger)", fontSize: 12, margin: 0 }}>{addError}</p>
                  )}
                  <Button type="submit" variant="default" size="sm" disabled={adding || !newKeyword.trim()}>
                    {adding ? (
                      <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} />
                    ) : (
                      <Plus size={14} />
                    )}
                    Ajouter
                  </Button>
                </form>
              </CardContent>
            </Card>

            {/* Keywords list */}
            <Card>
              <CardHeader>
                <CardTitle style={{ fontSize: 15 }}>Mots-clés surveillés</CardTitle>
              </CardHeader>
              <CardContent style={{ padding: "0 0 8px 0" }}>
                {loadingKeywords ? (
                  <div style={{ display: "flex", justifyContent: "center", padding: 24 }}>
                    <Loader2 size={20} style={{ animation: "spin 1s linear infinite", color: "var(--muted)" }} />
                  </div>
                ) : keywords.length === 0 ? (
                  <p style={{ color: "var(--muted)", fontSize: 13, textAlign: "center", padding: "16px 12px" }}>
                    Aucun mot-clé. Ajoutez-en un ci-dessus.
                  </p>
                ) : (
                  <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                    {keywords.map((kw) => (
                      <li
                        key={kw.id}
                        onClick={() => setSelectedKeywordId(kw.id)}
                        style={{
                          padding: "10px 16px",
                          cursor: "pointer",
                          borderBottom: "1px solid var(--border)",
                          background: selectedKeywordId === kw.id ? "var(--surface-high)" : "transparent",
                          transition: "background 0.15s",
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontWeight: 500, fontSize: 13, color: "var(--ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                              {kw.keyword}
                            </div>
                            <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4 }}>
                              <Badge variant={kw.status === "active" ? "success" : "secondary"} style={{ fontSize: 10 }}>
                                {kw.status === "active" ? "Actif" : "Pausé"}
                              </Badge>
                              {kw.match_count > 0 && (
                                <span style={{ fontSize: 11, color: "var(--muted)" }}>
                                  {kw.match_count} résultat{kw.match_count > 1 ? "s" : ""}
                                </span>
                              )}
                            </div>
                          </div>
                          <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
                            <button
                              onClick={(e) => { e.stopPropagation(); handleToggleStatus(kw); }}
                              disabled={actionLoading[`toggle-${kw.id}`]}
                              title={kw.status === "active" ? "Mettre en pause" : "Activer"}
                              style={{ background: "none", border: "none", cursor: "pointer", padding: 4, color: "var(--muted)", display: "flex" }}
                            >
                              {kw.status === "active" ? <ToggleRight size={16} style={{ color: "var(--success)" }} /> : <ToggleLeft size={16} />}
                            </button>
                            <button
                              onClick={(e) => { e.stopPropagation(); handleDeleteKeyword(kw.id); }}
                              disabled={actionLoading[`delete-kw-${kw.id}`]}
                              title="Supprimer"
                              style={{ background: "none", border: "none", cursor: "pointer", padding: 4, color: "var(--muted)", display: "flex" }}
                            >
                              <Trash2 size={14} />
                            </button>
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Right column — Posts */}
          <div>
            <Card>
              <CardHeader>
                <CardTitle style={{ fontSize: 15 }}>
                  Posts détectés
                  {selectedKeyword && (
                    <span style={{ fontWeight: 400, color: "var(--muted)", marginLeft: 8 }}>
                      — {selectedKeyword.keyword}
                    </span>
                  )}
                </CardTitle>
                <CardDescription>
                  {selectedKeyword
                    ? "Posts LinkedIn correspondant à ce mot-clé. Créez un lead depuis les auteurs pertinents."
                    : "Sélectionnez un mot-clé pour voir les posts détectés."}
                </CardDescription>
              </CardHeader>
              <CardContent>
                {!selectedKeywordId ? (
                  <div style={{ textAlign: "center", color: "var(--muted)", padding: "32px 0", fontSize: 13 }}>
                    Sélectionnez un mot-clé dans la liste de gauche.
                  </div>
                ) : loadingPosts ? (
                  <div style={{ display: "flex", justifyContent: "center", padding: 32 }}>
                    <Loader2 size={22} style={{ animation: "spin 1s linear infinite", color: "var(--muted)" }} />
                  </div>
                ) : posts.length === 0 ? (
                  <div style={{ textAlign: "center", color: "var(--muted)", padding: "32px 0", fontSize: 13 }}>
                    Aucun post détecté pour ce mot-clé pour l'instant.
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                    {posts.map((post) => (
                      <div
                        key={post.id}
                        style={{
                          border: "1px solid var(--border)",
                          borderRadius: "var(--radius-md, 0.5rem)",
                          padding: 14,
                          background: post.processed ? "var(--surface-low)" : "var(--surface)",
                          opacity: post.processed ? 0.75 : 1,
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            {/* Author */}
                            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                              <span style={{ fontWeight: 600, fontSize: 13, color: "var(--ink)" }}>
                                {post.author_name ?? "Auteur inconnu"}
                              </span>
                              {post.author_linkedin_url && (
                                <a
                                  href={post.author_linkedin_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  style={{ fontSize: 11, color: "var(--primary)", textDecoration: "underline" }}
                                >
                                  LinkedIn
                                </a>
                              )}
                            </div>

                            {/* Content */}
                            {post.post_content && (
                              <p style={{ fontSize: 13, color: "var(--ink)", margin: "0 0 8px 0", lineHeight: 1.5 }}>
                                {truncate(post.post_content)}
                              </p>
                            )}

                            {/* Meta */}
                            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                              {post.likes_count > 0 && (
                                <span style={{ fontSize: 12, color: "var(--muted)" }}>
                                  👍 {post.likes_count}
                                </span>
                              )}
                              {post.comments_count > 0 && (
                                <span style={{ fontSize: 12, color: "var(--muted)" }}>
                                  💬 {post.comments_count}
                                </span>
                              )}
                              {post.relevance_score !== null && (
                                <span style={{ fontSize: 12, color: "var(--muted)" }}>
                                  Pertinence : {Math.round(post.relevance_score * 100)}%
                                </span>
                              )}
                              {post.post_url && (
                                <a
                                  href={post.post_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  style={{ fontSize: 12, color: "var(--primary)", textDecoration: "underline" }}
                                >
                                  Voir le post
                                </a>
                              )}
                            </div>
                          </div>

                          {/* Action */}
                          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6, flexShrink: 0 }}>
                            {post.processed ? (
                              <Badge variant="success" style={{ gap: 4 }}>
                                <CheckCircle2 size={11} />
                                Traité
                              </Badge>
                            ) : (
                              <>
                                <Badge variant="warning">À traiter</Badge>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => handleCreateLead(post)}
                                  disabled={actionLoading[`lead-${post.id}`]}
                                >
                                  {actionLoading[`lead-${post.id}`] ? (
                                    <Loader2 size={12} style={{ animation: "spin 1s linear infinite" }} />
                                  ) : (
                                    <UserPlus size={12} />
                                  )}
                                  Créer un lead
                                </Button>
                              </>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      </div>

      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}

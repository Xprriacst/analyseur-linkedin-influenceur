"use client";

/**
 * Simulateur ManyChat — page de test de l'agent de qualification Instagram.
 *
 * Joue le rôle du prospect : chaque message envoyé ici rejoue le pipeline du
 * webhook ManyChat (persistance, réponse suggérée, garde-fou/autopilot) sur une
 * conversation fictive (`prospect_id` préfixé test:). Aucun appel réel à
 * l'API ManyChat ne part pour ces conversations — zéro risque d'envoi à un
 * vrai prospect. La conversation apparaît normalement dans l'Inbox.
 */

import { useEffect, useRef, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { authHeaders, supabase } from "../lib/supabase";

const DIRECT_API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ??
  "https://analyseur-linkedin-influenceur-api.onrender.com";

type SimMessage = {
  id: string;
  role: "in" | "out";
  source: string;
  text: string;
  kind: string;
  created_at: string;
};
type SimDraft = {
  id: string;
  reply: string;
  confidence: number | null;
  needs_human: boolean;
  status: string;
};

export default function ManyChatTestPage() {
  const [session, setSession] = useState<Session | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [prospectName, setProspectName] = useState("Jean Test");
  const [text, setText] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<SimMessage[]>([]);
  const [drafts, setDrafts] = useState<SimDraft[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setAuthChecked(true);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => sub.subscription.unsubscribe();
  }, []);

  async function loadThread(convId: string) {
    try {
      const [mRes, dRes] = await Promise.all([
        fetch(`${DIRECT_API_URL}/me/ig/conversations/${convId}/messages`, { headers: await authHeaders() }),
        fetch(`${DIRECT_API_URL}/me/ig/conversations/${convId}/drafts`, { headers: await authHeaders() }),
      ]);
      const mData = await mRes.json();
      const dData = await dRes.json();
      if (mRes.ok) setMessages(Array.isArray(mData) ? mData : []);
      if (dRes.ok) setDrafts(Array.isArray(dData) ? dData : []);
    } catch { /* non bloquant, le polling réessaie */ }
  }

  // La réponse suggérée est générée en tâche de fond côté serveur → on
  // rafraîchit le fil régulièrement pour voir arriver la réaction de l'agent.
  useEffect(() => {
    if (!conversationId) return;
    loadThread(conversationId);
    const t = setInterval(() => loadThread(conversationId), 4000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages.length]);

  async function sendAsProspect() {
    if (!text.trim()) return;
    setBusy(true); setError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/ig/test/inbound`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ text, prospect_name: prospectName || "Prospect Test" }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Envoi impossible");
      setText("");
      setConversationId(data.conversation_id);
      await loadThread(data.conversation_id);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const pendingDraft = drafts.find((d) => d.status === "pending") || null;

  if (!authChecked) return null;
  if (!session) {
    return (
      <div style={{ maxWidth: 560, margin: "80px auto", textAlign: "center", padding: 24 }}>
        <h1 style={{ fontSize: 20, marginBottom: 12 }}>🧪 Simulateur ManyChat</h1>
        <p style={{ opacity: 0.75, marginBottom: 16 }}>
          Connecte-toi d&apos;abord dans l&apos;application, puis reviens sur cette page.
        </p>
        <a href="/" style={{ textDecoration: "underline" }}>← Retour à l&apos;application</a>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 760, margin: "0 auto", padding: 24, display: "flex", flexDirection: "column", height: "100vh" }}>
      <header style={{ flex: "none", marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <h1 style={{ fontSize: 20 }}>🧪 Simulateur ManyChat</h1>
          <a href="/" style={{ fontSize: 13, textDecoration: "underline" }}>← Retour à l&apos;app</a>
        </div>
        <p style={{ fontSize: 13, opacity: 0.75, marginTop: 6 }}>
          Tu joues le <strong>prospect Instagram</strong> : chaque message passe par le même pipeline
          que ManyChat (persistance, réponse de l&apos;agent, garde-fou/autopilot). Rien ne part vers
          la vraie API ManyChat. La conversation apparaît dans l&apos;<a href="/" style={{ textDecoration: "underline" }}>Inbox</a> —
          c&apos;est là que tu valides les suggestions ou actives l&apos;autopilot.
        </p>
        <label style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10, fontSize: 13 }}>
          Nom du prospect simulé
          <input
            value={prospectName}
            onChange={(e) => setProspectName(e.target.value)}
            style={{ padding: "6px 10px", borderRadius: 8, border: "1px solid rgba(128,128,128,0.3)", fontSize: 13 }}
          />
        </label>
      </header>

      <section style={{ flex: 1, minHeight: 0, overflowY: "auto", border: "1px solid rgba(128,128,128,0.2)", borderRadius: 12, padding: 16, display: "flex", flexDirection: "column", gap: 8 }}>
        {messages.length === 0 && (
          <p style={{ margin: "auto", opacity: 0.6, fontSize: 14, textAlign: "center" }}>
            Écris un premier message en bas, comme si un prospect envoyait un DM.
          </p>
        )}
        {/* Point de vue prospect : ses messages (in) à droite, les réponses reçues (out) à gauche. */}
        {messages.map((m) => (
          <div key={m.id} style={{ alignSelf: m.role === "in" ? "flex-end" : "flex-start", maxWidth: "78%" }}>
            <div style={{
              padding: "8px 12px", borderRadius: 12, whiteSpace: "pre-wrap", fontSize: 14,
              background: m.role === "in" ? "rgba(90,120,255,0.18)" : "rgba(128,128,128,0.14)",
            }}>
              {m.text}
            </div>
            <div style={{ fontSize: 10, opacity: 0.5, textAlign: m.role === "in" ? "right" : "left", marginTop: 2 }}>
              {m.role === "in" ? "prospect (toi)" : `reçu de ${m.source === "agent" ? "l'agent (auto)" : "l'humain"}`}
              {m.created_at ? ` · ${new Date(m.created_at).toLocaleTimeString("fr-FR")}` : ""}
            </div>
          </div>
        ))}
        {pendingDraft && (
          <div style={{ alignSelf: "flex-start", fontSize: 12, opacity: 0.7, fontStyle: "italic" }}>
            💬 L&apos;agent a préparé une suggestion{pendingDraft.needs_human ? " (⚠️ escalade humaine)" : ""} —
            en attente de validation dans l&apos;Inbox…
          </div>
        )}
        {conversationId && !pendingDraft && messages.length > 0 && messages[messages.length - 1].role === "in" && (
          <div style={{ alignSelf: "flex-start", fontSize: 12, opacity: 0.6, fontStyle: "italic" }}>
            ⏳ L&apos;agent réfléchit…
          </div>
        )}
        <div ref={endRef} />
      </section>

      <footer style={{ flex: "none", marginTop: 12 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) sendAsProspect(); }}
            placeholder="Écris un DM comme le ferait un prospect… (⌘/Ctrl+Entrée pour envoyer)"
            rows={2}
            style={{ flex: 1, resize: "vertical", padding: 8, borderRadius: 8, border: "1px solid rgba(128,128,128,0.3)", fontSize: 14, fontFamily: "inherit" }}
          />
          <button
            onClick={sendAsProspect}
            disabled={busy || !text.trim()}
            style={{ padding: "10px 16px", borderRadius: 8, border: "none", background: "#5a78ff", color: "white", fontSize: 14, cursor: "pointer", opacity: busy || !text.trim() ? 0.5 : 1 }}
          >
            {busy ? "…" : "Envoyer en prospect"}
          </button>
        </div>
        {error && <div style={{ color: "#d33", fontSize: 13, marginTop: 6 }}>{error}</div>}
      </footer>
    </div>
  );
}

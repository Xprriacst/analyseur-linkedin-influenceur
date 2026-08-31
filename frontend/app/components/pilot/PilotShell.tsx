"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import PublishConfirmModal from "../PublishConfirmModal";
import PilotModeView, { type PilotPlan } from "./PilotModeView";
import { authHeaders } from "../../lib/supabase";

const DIRECT_API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ??
  "https://analyseur-linkedin-influenceur-api.onrender.com";

type LinkedInImageAttachment = { url: string; filename?: string; source?: string };

type PilotMeta = {
  post_id?: string | null;
  post_source?: string | null;
  post_text?: string;
  post_empty?: boolean;
  media_items?: LinkedInImageAttachment[];
  follow_handles?: Record<string, string>;
  linkedin_outreach_connected?: boolean;
  linkedin_publish_connected?: boolean;
  contacts_blocked_reason?: string | null;
};

type PilotTodayResponse = {
  plan: PilotPlan;
  meta: PilotMeta;
};

export type PilotShellProps = {
  mode: "pilot" | "expert";
  onModeChange: (mode: "pilot" | "expert") => void;
  onOpenGenerator: (seed: { topic: string; postText?: string; postId?: string }) => void;
  onOpenAssistant: (postText: string) => void;
};

function mediaToAttachments(items: PilotMeta["media_items"]): LinkedInImageAttachment[] {
  if (!items?.length) return [];
  return items
    .map((item, i) => {
      const url = item.url || (item as { data_url?: string }).data_url;
      if (!url) return null;
      return {
        id: `pilot-${i}`,
        url,
        filename: item.filename || `image-${i + 1}.jpg`,
        source: item.source || "upload",
      };
    })
    .filter(Boolean) as LinkedInImageAttachment[];
}

export default function PilotShell({
  mode,
  onModeChange,
  onOpenGenerator,
  onOpenAssistant,
}: PilotShellProps) {
  const [plan, setPlan] = useState<PilotPlan | null>(null);
  const [meta, setMeta] = useState<PilotMeta | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [publishOpen, setPublishOpen] = useState(false);
  const [publishing, setPublishing] = useState(false);

  const loadPlan = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/pilot/today`, {
        headers: await authHeaders(),
      });
      const data = (await res.json()) as PilotTodayResponse;
      if (!res.ok) throw new Error((data as { detail?: string }).detail || "Chargement impossible");
      setPlan(data.plan);
      setMeta(data.meta);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Chargement impossible";
      setLoadError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (mode === "pilot") void loadPlan();
  }, [mode, loadPlan]);

  const postText = meta?.post_text || (plan ? `${plan.post.hook}\n\n${plan.post.body}`.trim() : "");
  const images = mediaToAttachments(meta?.media_items);

  async function doPublish(text: string) {
    setPublishing(true);
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/linkedin/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({
          content: text,
          draft: false,
          images: images.map(({ url }) => url),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Publication impossible");
      toast.success("Publié sur LinkedIn");
      setPublishOpen(false);
      void loadPlan();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Publication impossible");
    } finally {
      setPublishing(false);
    }
  }

  async function handleInvite(contactId: string) {
    if (!meta?.linkedin_outreach_connected) {
      toast.error(meta?.contacts_blocked_reason || "Connecte LinkedIn pour inviter.");
      return;
    }
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/leads/${contactId}/invite`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({}),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Invitation impossible");
      toast.success("Invitation mise en file — envoi cadencé");
      void loadPlan();
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Invitation impossible");
    }
  }

  function handlePublishClick() {
    if (meta?.post_empty || !postText.trim()) {
      onOpenGenerator({ topic: "" });
      return;
    }
    if (!meta?.linkedin_publish_connected) {
      toast.error("Connecte LinkedIn pour publier (Mon profil → Connexions).");
      return;
    }
    setPublishOpen(true);
  }

  if (loading && !plan) {
    return (
      <div className="pilot-root">
        <div className="pilot-inner" style={{ padding: "48px 24px", textAlign: "center", color: "#86868b" }}>
          Chargement de ton plan du jour…
        </div>
      </div>
    );
  }

  if (loadError && !plan) {
    return (
      <div className="pilot-root">
        <div className="pilot-inner" style={{ padding: "48px 24px", textAlign: "center" }}>
          <p style={{ color: "#86868b", marginBottom: 16 }}>{loadError}</p>
          <button type="button" className="pilot-btn pilot-btn-primary" onClick={() => void loadPlan()}>
            Réessayer
          </button>
        </div>
      </div>
    );
  }

  if (!plan) return null;

  return (
    <>
      <PilotModeView
        plan={plan}
        mode={mode}
        onModeChange={onModeChange}
        postEmpty={Boolean(meta?.post_empty)}
        contactsBlockedReason={meta?.contacts_blocked_reason || undefined}
        onPublish={handlePublishClick}
        onEditPost={() => {
          if (!postText.trim()) {
            onOpenGenerator({ topic: "" });
            return;
          }
          onOpenGenerator({
            topic: postText.slice(0, 120),
            postText,
            postId: meta?.post_id || undefined,
          });
        }}
        onRegeneratePost={() => {
          const topic = plan.post.hook || plan.post.body.slice(0, 120) || "";
          onOpenAssistant(postText || topic);
        }}
        onInvite={handleInvite}
      />
      {publishOpen && (
        <PublishConfirmModal
          text={postText}
          images={images}
          busy={publishing}
          crossNetworks={false}
          onClose={() => setPublishOpen(false)}
          onConfirm={(text) => void doPublish(text)}
        />
      )}
    </>
  );
}

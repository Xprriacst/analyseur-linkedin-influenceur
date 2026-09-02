"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import PublishConfirmModal from "../PublishConfirmModal";
import PilotModeView, {
  type PilotPlan,
  type PilotFollowSuggestion,
  type PilotProspectAgent,
} from "./PilotModeView";
import { PilotNav, type PilotNavTab } from "./PilotNav";
import { PilotProfilePane } from "./PilotProfilePane";
import { authHeaders } from "../../lib/supabase";

const DIRECT_API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ??
  "https://analyseur-linkedin-influenceur-api.onrender.com";

const PILOT_POLL_MS = 30_000;

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
  prospect_agent?: PilotProspectAgent | null;
  is_pilote_landing?: boolean;
};

type PilotTodayResponse = {
  plan: PilotPlan;
  meta: PilotMeta;
};

export type PilotShellProps = {
  interfaceMode: "pilot" | "expert";
  onInterfaceModeChange: (mode: "pilot" | "expert") => void;
  onOpenGenerator: (seed: { topic: string; postText?: string; postId?: string }) => void;
  onOpenAssistant: (postText: string) => void;
  onUpgrade: () => void;
  upgradeBusy?: boolean;
  /** Tier Pilote gratuit : actions réelles désactivées (aperçu seulement). */
  actionsLocked?: boolean;
  /** Site dev : le bandeau fixe de 30 px recouvrirait le haut de la nav. */
  devBanner?: boolean;
  /** Compte connecté + déconnexion : le Mode Pilote n'a pas d'entête. */
  userEmail?: string;
  onSignOut?: () => void;
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
  interfaceMode,
  onInterfaceModeChange,
  onOpenGenerator,
  onOpenAssistant,
  onUpgrade,
  upgradeBusy = false,
  actionsLocked = false,
  devBanner = false,
  userEmail,
  onSignOut,
}: PilotShellProps) {
  const layoutClass = `pilot-app-layout${devBanner ? " pilot-dev-offset" : ""}`;
  const [navTab, setNavTab] = useState<PilotNavTab>("today");
  const [plan, setPlan] = useState<PilotPlan | null>(null);
  const [meta, setMeta] = useState<PilotMeta | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [publishOpen, setPublishOpen] = useState(false);
  const [publishing, setPublishing] = useState(false);

  // Suggestions « à suivre » — chargées au PREMIER dépliage seulement.
  const [followSuggestions, setFollowSuggestions] = useState<PilotFollowSuggestion[]>([]);
  const [followEmptyReason, setFollowEmptyReason] = useState<string | null>(null);
  const [followLoading, setFollowLoading] = useState(false);
  const [followError, setFollowError] = useState("");
  const [followLoaded, setFollowLoaded] = useState(false);
  const [followedHandles, setFollowedHandles] = useState<string[]>([]);
  const [followCapReached, setFollowCapReached] = useState(false);

  const loadPlan = useCallback(async (opts?: { silent?: boolean }) => {
    if (!opts?.silent) {
      setLoading(true);
      setLoadError("");
    }
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
      if (!opts?.silent) setLoadError(message);
    } finally {
      if (!opts?.silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (interfaceMode !== "pilot") return;
    void loadPlan();
    const id = window.setInterval(() => void loadPlan({ silent: true }), PILOT_POLL_MS);
    return () => window.clearInterval(id);
  }, [interfaceMode, loadPlan]);

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

  const loadFollowSuggestions = useCallback(async () => {
    if (followLoaded || followLoading) return;
    setFollowLoading(true);
    setFollowError("");
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/follow-suggestions`, {
        headers: await authHeaders(),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Chargement impossible");
      setFollowSuggestions(data.suggestions || []);
      setFollowEmptyReason(data.empty_reason ?? null);
      setFollowCapReached((data.followed_count || 0) >= (data.cap || 5));
      setFollowLoaded(true);
    } catch (err: unknown) {
      setFollowError(err instanceof Error ? err.message : "Chargement impossible");
    } finally {
      setFollowLoading(false);
    }
  }, [followLoaded, followLoading]);

  async function handleFollowProfile(handle: string) {
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/followed-influencers`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ handle }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Impossible de suivre ce profil");
      setFollowedHandles((prev) => (prev.includes(handle) ? prev : [...prev, handle]));
      toast.success("Ajouté à ta veille");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Impossible de suivre ce profil");
    }
  }

  async function handleInvite(contactId: string) {
    if (actionsLocked) {
      toast.message("Réservé aux abonnés premium — passe en premium pour inviter.");
      return;
    }
    if (contactId.startsWith("sim-")) {
      toast.message("Connecte LinkedIn dans Mon profil pour inviter ce prospect.");
      return;
    }
    if (!meta?.linkedin_outreach_connected) {
      toast.error("Connecte LinkedIn pour inviter (Mon profil → Connexions).");
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
    if (actionsLocked) {
      toast.message("Réservé aux abonnés premium — passe en premium pour publier.");
      return;
    }
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
      <div className={layoutClass}>
        <PilotNav
          activeTab={navTab}
          onTabChange={setNavTab}
          onUpgrade={onUpgrade}
          upgradeBusy={upgradeBusy}
          interfaceMode={interfaceMode}
          onInterfaceModeChange={onInterfaceModeChange}
        />
        <div className="pilot-app-main">
          <div className="pilot-inner" style={{ padding: "48px 24px", textAlign: "center", color: "#86868b" }}>
            Chargement de ton plan du jour…
          </div>
        </div>
      </div>
    );
  }

  if (loadError && !plan) {
    return (
      <div className={layoutClass}>
        <PilotNav
          activeTab={navTab}
          onTabChange={setNavTab}
          onUpgrade={onUpgrade}
          upgradeBusy={upgradeBusy}
          interfaceMode={interfaceMode}
          onInterfaceModeChange={onInterfaceModeChange}
        />
        <div className="pilot-app-main">
          <div className="pilot-inner" style={{ padding: "48px 24px", textAlign: "center" }}>
            <p style={{ color: "#86868b", marginBottom: 16 }}>{loadError}</p>
            <button type="button" className="pilot-btn pilot-btn-primary" onClick={() => void loadPlan()}>
              Réessayer
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!plan) return null;

  return (
    <div className={layoutClass}>
      <PilotNav
        activeTab={navTab}
        onTabChange={setNavTab}
        onUpgrade={onUpgrade}
        upgradeBusy={upgradeBusy}
        interfaceMode={interfaceMode}
        onInterfaceModeChange={onInterfaceModeChange}
      />
      <div className="pilot-app-main">
        {navTab === "profile" ? (
          <PilotProfilePane
            userEmail={userEmail}
            onSignOut={onSignOut}
            strategy={plan.strategy}
            followSuggestions={followSuggestions}
            followLoading={followLoading}
            followError={followError}
            followEmptyReason={followEmptyReason}
            followedHandles={followedHandles}
            followCapReached={followCapReached}
            onFollowPanelOpen={loadFollowSuggestions}
            onFollowProfile={(handle) => void handleFollowProfile(handle)}
          />
        ) : (
          <PilotModeView
            plan={plan}
            mode="pilot"
            hideModeToggle
            actionsLocked={actionsLocked}
            postEmpty={Boolean(meta?.post_empty)}
            contactsBlockedReason={meta?.contacts_blocked_reason || undefined}
            prospectAgent={meta?.prospect_agent ?? null}
            onPublish={handlePublishClick}
            onEditPost={() => {
              if (actionsLocked) {
                toast.message("Réservé aux abonnés premium — passe en premium pour modifier.");
                return;
              }
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
              if (actionsLocked) {
                toast.message("Réservé aux abonnés premium — passe en premium pour régénérer.");
                return;
              }
              const topic = plan.post.hook || plan.post.body.slice(0, 120) || "";
              onOpenAssistant(postText || topic);
            }}
            onInvite={handleInvite}
          />
        )}
      </div>
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
    </div>
  );
}

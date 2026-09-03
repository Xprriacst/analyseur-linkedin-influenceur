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
  showUpgradeButton?: boolean;
  /** Tier Pilote gratuit : actions réelles désactivées (aperçu seulement). */
  actionsLocked?: boolean;
  isPremium?: boolean;
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
  showUpgradeButton = true,
  actionsLocked = false,
  isPremium = false,
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
  const [connectingLinkedIn, setConnectingLinkedIn] = useState(false);

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

  async function connectLinkedIn() {
    setConnectingLinkedIn(true);
    try {
      const redirect = `${window.location.origin}${window.location.pathname}?linkedin_outreach=connected`;
      const res = await fetch(`${DIRECT_API_URL}/me/linkedin/outreach/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ redirect_url: redirect }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Connexion impossible");
      window.location.href = data.auth_url; // Unipile gère l'auth LinkedIn puis renvoie vers l'app
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Connexion impossible");
      setConnectingLinkedIn(false);
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
          showUpgradeButton={showUpgradeButton}
          interfaceMode={interfaceMode}
          onInterfaceModeChange={onInterfaceModeChange}
        />
        <div className="pilot-app-main">
          {/* Squelette à la forme RÉELLE de la vue du jour (salutation, semaine,
              post, contacts) plutôt qu'une phrase grise centrée : l'écran ne
              saute plus au moment où le plan arrive, il se remplit. Mêmes
              primitives `.sk` que le mode Expert (globals.css, ALE-266) — pas
              un second système d'états de chargement.
              `aria-hidden` + `role="status"` : le lecteur d'écran entend une
              phrase, pas dix-sept blocs vides. */}
          <div className="pilot-inner pilot-skeleton" role="status" aria-live="polite">
            <span className="sr-only">Chargement de ton plan du jour…</span>
            <div className="pilot-hero" aria-hidden>
              <div className="pilot-hero-copy sk-list">
                <div className="sk line sm" style={{ width: 110 }} />
                <div className="sk line" style={{ width: "62%", height: 26, marginTop: 14 }} />
                <div className="sk line" style={{ width: "84%", marginTop: 12 }} />
              </div>
              <div className="pilot-skeleton-week">
                <div className="sk" style={{ width: 96, height: 12, borderRadius: 999 }} />
                <div className="sk line sm" style={{ width: 74, marginTop: 10 }} />
              </div>
            </div>

            <div className="pilot-desk" aria-hidden>
              <section className="pilot-section">
                <div className="pilot-section-head">
                  <div className="sk line sm" style={{ width: 96 }} />
                  <div className="sk" style={{ width: 68, height: 18, borderRadius: 999 }} />
                </div>
                <article className="pilot-post-card">
                  <div className="pilot-post-card-inner sk-list">
                    <div className="pilot-skeleton-author">
                      <div className="sk circle" style={{ width: 40, height: 40 }} />
                      <div style={{ flex: 1 }}>
                        <div className="sk line sm" style={{ width: "44%" }} />
                        <div className="sk line sm" style={{ width: "66%", marginTop: 7 }} />
                      </div>
                    </div>
                    <div className="sk line" style={{ width: "92%", marginTop: 18 }} />
                    <div className="sk line" style={{ width: "100%", marginTop: 10 }} />
                    <div className="sk line" style={{ width: "97%", marginTop: 10 }} />
                    <div className="sk line" style={{ width: "58%", marginTop: 10 }} />
                  </div>
                </article>
              </section>

              <section className="pilot-section">
                <div className="pilot-section-head">
                  <div className="sk line sm" style={{ width: 112 }} />
                </div>
                <div className="sk-list">
                  {[0, 1, 2].map((i) => (
                    <div key={i} className="pilot-skeleton-contact">
                      <div className="sk circle" style={{ width: 34, height: 34 }} />
                      <div style={{ flex: 1 }}>
                        <div className="sk line sm" style={{ width: "52%" }} />
                        <div className="sk line sm" style={{ width: "78%", marginTop: 7 }} />
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            </div>
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
          showUpgradeButton={showUpgradeButton}
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
        showUpgradeButton={showUpgradeButton}
        interfaceMode={interfaceMode}
        onInterfaceModeChange={onInterfaceModeChange}
      />
      <div className="pilot-app-main">
        {navTab === "profile" ? (
          <PilotProfilePane
            userEmail={userEmail}
            onSignOut={onSignOut}
            isPremium={isPremium}
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
            onConnectLinkedIn={connectLinkedIn}
            connectingLinkedIn={connectingLinkedIn}
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

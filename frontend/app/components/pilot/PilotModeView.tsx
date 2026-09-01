"use client";

import { useCallback, useMemo, useState } from "react";
import { Toaster, toast } from "sonner";
import {
  Check,
  ChevronDown,
  Loader2,
  PenLine,
  RefreshCw,
  Send,
  Sparkles,
  Target,
  UserPlus,
  Users,
} from "lucide-react";
import "./pilot-mode.css";

export type PilotAuthor = {
  name: string;
  headline: string;
  initials: string;
  avatarUrl?: string;
};

export type PilotFollowProfile = {
  id: string;
  name: string;
  handle: string;
  reason: string;
  initials: string;
  accent: string;
};

/** Profil suggéré à suivre — déjà analysé par un autre compte, matché sur la niche.
 *  Volontairement HORS de `PilotPlan` : le plan du jour vient de
 *  `GET /me/pilot/today`, ces suggestions d'un appel séparé et paresseux. */
export type PilotFollowSuggestion = {
  handle: string;
  name: string;
  headline: string;
  profile_url: string;
  follower_count: number;
  matched_keywords: string[];
};

export type PilotContact = {
  id: string;
  name: string;
  role: string;
  company: string;
  score: number;
  initials: string;
  accent: string;
  message: string;
};

export type PilotPost = {
  structure: string;
  hook: string;
  body: string;
};

export type PilotStrategy = {
  profiles: string[];
  frequency: string;
  target: string;
  structureHint: string;
};

export type PilotPlan = {
  userName: string;
  dayNumber: number;
  weekNumber: number;
  weeklyDone: number;
  weeklyTotal: number;
  author: PilotAuthor;
  post: PilotPost;
  followProfiles: PilotFollowProfile[];
  contacts: PilotContact[];
  strategy: PilotStrategy;
};

/** Initiales d'un nom — les suggestions arrivent du serveur sans champ `initials`
 *  (contrairement aux lignes du plan du jour, qui sont composées côté backend). */
function initialsOf(name: string): string {
  const parts = (name || "").trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

type InterfaceMode = "pilot" | "expert";

type PilotModeViewProps = {
  plan: PilotPlan;
  preview?: boolean;
  mode?: InterfaceMode;
  onModeChange?: (mode: InterfaceMode) => void;
  postEmpty?: boolean;
  contactsBlockedReason?: string;
  onPublish?: () => void;
  onEditPost?: () => void;
  onRegeneratePost?: () => void;
  onInvite?: (contactId: string) => void;
  // Suggestions « à suivre » : chargées PARESSEUSEMENT, au premier dépliage.
  // La vue simplifiée reste épurée (décision du 2026-08-31, « rail contacts
  // seuls ») ; on ne paie donc rien tant que le client ne demande pas à voir.
  followSuggestions?: PilotFollowSuggestion[];
  followLoading?: boolean;
  followError?: string;
  followedHandles?: string[];
  followCapReached?: boolean;
  onFollowPanelOpen?: () => void;
  onFollowProfile?: (handle: string) => void;
};

export default function PilotModeView({
  plan,
  preview = false,
  mode: controlledMode,
  onModeChange,
  postEmpty = false,
  contactsBlockedReason,
  onPublish,
  onEditPost,
  onRegeneratePost,
  onInvite,
  followSuggestions = [],
  followLoading = false,
  followError = "",
  followedHandles = [],
  followCapReached = false,
  onFollowPanelOpen,
  onFollowProfile,
}: PilotModeViewProps) {
  const [internalMode, setInternalMode] = useState<InterfaceMode>("pilot");
  const mode = controlledMode ?? internalMode;
  const setMode = onModeChange ?? setInternalMode;

  const [strategyOpen, setStrategyOpen] = useState(false);
  const [followOpen, setFollowOpen] = useState(false);
  const [expandedContactId, setExpandedContactId] = useState<string | null>(null);
  const [invited, setInvited] = useState<Set<string>>(new Set());
  const [published, setPublished] = useState(false);

  const postParagraphs = useMemo(
    () => plan.post.body.split(/\n\n+/).map((p) => p.trim()).filter(Boolean),
    [plan.post.body],
  );

  const handleAction = useCallback(
    (label: string, fn?: () => void) => {
      fn?.();
      if (preview) {
        toast(`${label} — simulé`);
      }
    },
    [preview],
  );

  const hasPostContent = !postEmpty && Boolean(plan.post.hook.trim() || plan.post.body.trim());

  const toaster = (
    <Toaster
      theme="light"
      invert
      position="bottom-center"
      offset={28}
      mobileOffset={16}
      visibleToasts={3}
      toastOptions={{ duration: 2400 }}
    />
  );

  const header = (
    <header className="pilot-header">
      <div className="pilot-header-inner">
        <div className="pilot-brand">
          <span className="pilot-brand-mark" aria-hidden />
          <span className="pilot-brand-name">Cibl</span>
          {preview && <span className="pilot-preview-chip">Maquette</span>}
        </div>

        <div className="pilot-header-meta">
          {mode === "pilot" && (
            <span className="pilot-day-chip">
              Jour {plan.dayNumber}
              <span className="pilot-day-chip-muted"> · S{plan.weekNumber}</span>
            </span>
          )}
          <div className="pilot-mode-toggle" role="tablist" aria-label="Mode d'interface">
            <button
              type="button"
              role="tab"
              aria-selected={mode === "pilot"}
              className={mode === "pilot" ? "active" : ""}
              onClick={() => setMode("pilot")}
            >
              Pilote
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "expert"}
              className={mode === "expert" ? "active" : ""}
              onClick={() => setMode("expert")}
            >
              Expert
            </button>
          </div>
        </div>
      </div>
    </header>
  );

  if (mode === "expert" && preview) {
    return (
      <div className="pilot-expert-shell">
        {toaster}
        {header}
        <div className="pilot-expert-placeholder">
          <h1>Mode Expert</h1>
          <p>
            L’app actuelle s’affiche ici — sidebar, Contenu, Prospection, Inbox.
            Cette maquette ne reproduit pas la vue complète.
          </p>
        </div>
      </div>
    );
  }

  const weekDots = Array.from({ length: plan.weeklyTotal }, (_, i) => i < plan.weeklyDone);

  return (
    <div className="pilot-root">
      {toaster}
      <div className="pilot-aurora" aria-hidden>
        <span className="pilot-orb pilot-orb-a" />
        <span className="pilot-orb pilot-orb-b" />
        <span className="pilot-orb pilot-orb-c" />
      </div>
      {header}

      <div className="pilot-inner">
        <div className="pilot-hero">
          <div className="pilot-hero-copy">
            <span className="pilot-ai-chip">
              <Sparkles size={12} strokeWidth={2.2} aria-hidden />
              Généré pour toi
            </span>
            <h1 className="pilot-greeting">Bonjour {plan.userName}.</h1>
            <p className="pilot-greeting-sub">
              {hasPostContent
                ? <>Ton post est prêt. {plan.contacts.length} personne{plan.contacts.length > 1 ? "s" : ""} à contacter.<span className="pilot-greeting-rest"> C’est tout.</span></>
                : <>Pas encore de post du jour — lance une génération.<span className="pilot-greeting-rest"> Le reste de ton plan est prêt.</span></>}
            </p>
          </div>
          <div className="pilot-week" aria-label="Objectif de la semaine">
            <div className="pilot-week-dots">
              {weekDots.map((done, i) => (
                <span
                  key={i}
                  className={`pilot-week-dot${done ? " done" : " next"}`}
                  aria-label={done ? `Action ${i + 1} faite` : `Action ${i + 1} restante`}
                />
              ))}
            </div>
            <span className="pilot-week-label">
              {plan.weeklyDone}/{plan.weeklyTotal} cette semaine
            </span>
          </div>
        </div>

        <div className="pilot-desk">
          <section className="pilot-section" aria-labelledby="pilot-post-title">
          <div className="pilot-section-head">
            <h2 className="pilot-section-label" id="pilot-post-title">
              Post du jour
            </h2>
            <span className="pilot-badge">{plan.post.structure}</span>
          </div>

          <article className="pilot-post-card" aria-label="Post à publier">
            <div className="pilot-post-card-inner">
              {hasPostContent ? (
                <>
                  <div className="pilot-post-author">
                    <div className="pilot-avatar pilot-avatar-author" aria-hidden>
                      {plan.author.avatarUrl ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={plan.author.avatarUrl} alt="" />
                      ) : (
                        plan.author.initials
                      )}
                    </div>
                    <div>
                      <div className="pilot-post-name">{plan.author.name}</div>
                      <div className="pilot-post-headline">{plan.author.headline}</div>
                    </div>
                  </div>
                  <p className="pilot-post-hook">{plan.post.hook}</p>
                  {postParagraphs.map((paragraph, i) => (
                    <p key={i} className="pilot-post-p">
                      {paragraph}
                    </p>
                  ))}
                </>
              ) : (
                <div className="pilot-empty-block">
                  <p className="pilot-empty-title">Aucun post prêt</p>
                  <p className="pilot-empty-copy">
                    Génère un post dans le Générateur ou active l’idée du jour — rien n’est inventé ici.
                  </p>
                </div>
              )}
              <div className="pilot-actions">
                <button
                  type="button"
                  className={`pilot-btn pilot-btn-primary${published ? " done" : ""}`}
                  onClick={() => {
                    if (hasPostContent) setPublished(true);
                    handleAction("Publication", onPublish);
                  }}
                >
                  {published ? <Check size={16} strokeWidth={2.4} /> : <Send size={16} />}
                  {published ? "Publié" : hasPostContent ? "Publier" : "Ouvrir le Générateur"}
                </button>
                {hasPostContent && (
                  <>
                    <button
                      type="button"
                      className="pilot-btn pilot-btn-ghost"
                      onClick={() => handleAction("Modification", onEditPost)}
                    >
                      <PenLine size={15} />
                      Modifier
                    </button>
                    <button
                      type="button"
                      className="pilot-btn pilot-btn-ghost"
                      onClick={() => handleAction("Régénération", onRegeneratePost)}
                    >
                      <RefreshCw size={15} />
                      Autre angle
                    </button>
                  </>
                )}
              </div>
            </div>
          </article>
        </section>

        <aside className="pilot-aside">
          <section className="pilot-section" aria-labelledby="pilot-contacts-title">
            <div className="pilot-section-head">
              <h2 className="pilot-section-label" id="pilot-contacts-title">
                À contacter
              </h2>
              <span className="pilot-section-hint">{plan.contacts.length} aujourd’hui</span>
            </div>
            <div className="pilot-contacts-list">
              {contactsBlockedReason && (
                <div className="pilot-empty-block pilot-empty-block-inline">
                  <p className="pilot-empty-copy">{contactsBlockedReason}</p>
                </div>
              )}
              {!contactsBlockedReason && plan.contacts.length === 0 && (
                <div className="pilot-empty-block pilot-empty-block-inline">
                  <p className="pilot-empty-copy">
                    Aucun lead invitable pour l’instant — importe une recherche ou collecte des commentaires, puis laisse le scoring ICP faire son travail.
                  </p>
                </div>
              )}
              {plan.contacts.map((contact) => {
                const isInvited = invited.has(contact.id);
                const isOpen = expandedContactId === contact.id;
                const panelId = `pilot-contact-panel-${contact.id}`;
                return (
                  <article
                    key={contact.id}
                    className={`pilot-contact-block${isOpen ? " open" : ""}${isInvited ? " invited" : ""}`}
                  >
                    <button
                      type="button"
                      className="pilot-contact-summary"
                      aria-expanded={isOpen}
                      aria-controls={panelId}
                      onClick={() =>
                        setExpandedContactId((current) =>
                          current === contact.id ? null : contact.id,
                        )
                      }
                    >
                      <div className="pilot-avatar" aria-hidden>
                        {contact.initials}
                      </div>
                      <div className="pilot-contact-info">
                        <h3>{contact.name}</h3>
                        <p>
                          {contact.role}
                          {contact.company ? ` · ${contact.company}` : ""}
                        </p>
                      </div>
                      <span className="pilot-score">{contact.score}</span>
                      <ChevronDown size={16} className="pilot-contact-chevron" aria-hidden />
                    </button>
                    <div id={panelId} className={`pilot-contact-panel${isOpen ? " open" : ""}`}>
                      {isOpen && (
                        <div className="pilot-contact-panel-inner">
                          <p className="pilot-message-preview">{contact.message}</p>
                          <button
                            type="button"
                            className={`pilot-btn pilot-btn-primary pilot-btn-invite${isInvited ? " done" : ""}`}
                            onClick={() => {
                              setInvited((prev) => new Set(prev).add(contact.id));
                              handleAction(`Invitation à ${contact.name}`, () =>
                                onInvite?.(contact.id),
                              );
                            }}
                            disabled={isInvited || Boolean(contactsBlockedReason)}
                          >
                            {isInvited ? <Check size={15} /> : <UserPlus size={15} />}
                            {isInvited ? "Invitation envoyée" : "Inviter"}
                          </button>
                        </div>
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
          </section>
        </aside>
        </div>

        {/* Influenceurs à suivre — REPLIÉ par défaut. La vue simplifiée garde le rail
            contacts seul (décision du 2026-08-31) ; les suggestions existent
            bien en Mode Pilote, mais il faut cliquer pour les afficher.
            ⚠️ `<section>` SANS `aria-labelledby`, comme « Ta stratégie » : elle
            ne devient donc pas une `region` accessible, et l'assertion du spec
            e2e sur l'absence de la région « À suivre » reste vraie. */}
        <section className="pilot-section-strategy">
          <button
            type="button"
            className={`pilot-strategy-toggle${followOpen ? " open" : ""}`}
            aria-expanded={followOpen}
            aria-controls="pilot-follow-panel"
            onClick={() => {
              setFollowOpen((v) => {
                // Chargement paresseux : la requête ne part qu'à l'ouverture,
                // jamais au chargement de l'accueil.
                if (!v) onFollowPanelOpen?.();
                return !v;
              });
            }}
          >
            <span>
              <Users size={15} strokeWidth={2.2} />
              Influenceurs à suivre
            </span>
            <ChevronDown size={16} className="chevron" />
          </button>
          <div
            id="pilot-follow-panel"
            className={`pilot-strategy-panel${followOpen ? " open" : ""}`}
          >
            <div className="pilot-strategy-panel-inner">
              {followOpen && (
                <div style={{ padding: "0 4px 12px" }}>
                  {followLoading && (
                    <div className="pilot-empty-block pilot-empty-block-inline">
                      <p className="pilot-empty-copy">
                        <Loader2 size={14} className="spinning" /> Recherche de profils de ta niche…
                      </p>
                    </div>
                  )}
                  {!followLoading && followError && (
                    <div className="pilot-empty-block pilot-empty-block-inline">
                      <p className="pilot-empty-copy">{followError}</p>
                    </div>
                  )}
                  {!followLoading && !followError && followSuggestions.length === 0 && (
                    <div className="pilot-empty-block pilot-empty-block-inline">
                      <p className="pilot-empty-copy">
                        Aucun profil à te proposer pour l’instant — complète ton profil éditorial
                        (ton secteur, ta cible, ton offre) et on te suggérera des comptes de ta niche.
                      </p>
                    </div>
                  )}
                  {!followLoading && followSuggestions.length > 0 && (
                    <div className="pilot-follow-list">
                      {followSuggestions.map((profile) => {
                        const isFollowed = followedHandles.includes(profile.handle);
                        return (
                          <div key={profile.handle} className="pilot-follow-row">
                            <div className="pilot-avatar" aria-hidden>
                              {initialsOf(profile.name)}
                            </div>
                            <div className="pilot-follow-info">
                              <h3>{profile.name}</h3>
                              <p>
                                {profile.headline || profile.handle}
                                {profile.matched_keywords.length > 0
                                  ? ` — correspond à ta niche : ${profile.matched_keywords.join(" · ")}`
                                  : ""}
                              </p>
                            </div>
                            {/* `aria-label` : plusieurs boutons « Suivre » identiques
                                sont indistinguables au lecteur d'écran (et au test). */}
                            <button
                              type="button"
                              className={`pilot-btn pilot-btn-follow${isFollowed ? " done" : ""}`}
                              aria-label={`Suivre ${profile.name}`}
                              disabled={isFollowed || (followCapReached && !isFollowed)}
                              title={
                                followCapReached && !isFollowed
                                  ? "Tu suis déjà le maximum d’influenceurs. Retires-en un pour en ajouter."
                                  : "Surveiller ses nouveaux posts"
                              }
                              onClick={() =>
                                handleAction(`Suivre ${profile.name}`, () =>
                                  onFollowProfile?.(profile.handle),
                                )
                              }
                            >
                              {isFollowed ? <Check size={14} /> : <UserPlus size={14} />}
                              {isFollowed ? "Suivi" : "Suivre"}
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </section>

        <section className="pilot-section-strategy">
          <button
            type="button"
            className={`pilot-strategy-toggle${strategyOpen ? " open" : ""}`}
            aria-expanded={strategyOpen}
            aria-controls="pilot-strategy-panel"
            onClick={() => setStrategyOpen((v) => !v)}
          >
            <span>
              <Target size={15} strokeWidth={2.2} />
              Ta stratégie
            </span>
            <ChevronDown size={16} className="chevron" />
          </button>
          <div
            id="pilot-strategy-panel"
            className={`pilot-strategy-panel${strategyOpen ? " open" : ""}`}
          >
            <div className="pilot-strategy-panel-inner">
              <ul className="pilot-strategy-list">
                <li>
                  <strong>Cible</strong>
                  {plan.strategy.target}
                </li>
                <li>
                  <strong>Rythme</strong>
                  {plan.strategy.frequency}
                </li>
                <li>
                  <strong>Structure</strong>
                  {plan.strategy.structureHint}
                </li>
              </ul>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

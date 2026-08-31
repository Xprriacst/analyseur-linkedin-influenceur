"use client";

import { useCallback, useState } from "react";
import { Outfit } from "next/font/google";
import {
  Check,
  ChevronDown,
  Globe,
  Linkedin,
  MessageCircle,
  PenLine,
  RefreshCw,
  Repeat2,
  Send,
  Sparkles,
  Target,
  ThumbsUp,
  TrendingUp,
  UserPlus,
  Users,
} from "lucide-react";
import "./pilot-mode.css";

const outfit = Outfit({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800", "900"],
  variable: "--font-pilot",
});

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

type InterfaceMode = "pilot" | "expert";

type PilotModeViewProps = {
  plan: PilotPlan;
  preview?: boolean;
  mode?: InterfaceMode;
  onModeChange?: (mode: InterfaceMode) => void;
  onPublish?: () => void;
  onEditPost?: () => void;
  onRegeneratePost?: () => void;
  onInvite?: (contactId: string) => void;
  onFollowProfile?: (profileId: string) => void;
};

export default function PilotModeView({
  plan,
  preview = false,
  mode: controlledMode,
  onModeChange,
  onPublish,
  onEditPost,
  onRegeneratePost,
  onInvite,
  onFollowProfile,
}: PilotModeViewProps) {
  const [internalMode, setInternalMode] = useState<InterfaceMode>("pilot");
  const mode = controlledMode ?? internalMode;
  const setMode = onModeChange ?? setInternalMode;

  const [strategyOpen, setStrategyOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [followed, setFollowed] = useState<Set<string>>(new Set());
  const [invited, setInvited] = useState<Set<string>>(new Set());
  const [published, setPublished] = useState(false);

  const showToast = useCallback((message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(null), 2400);
  }, []);

  const handleAction = useCallback(
    (label: string, fn?: () => void) => {
      if (fn) {
        fn();
        return;
      }
      showToast(`${label} — simulé`);
    },
    [showToast],
  );

  const header = (
    <header className="pilot-header">
      <div className="pilot-header-inner">
        <div className="pilot-brand">
          <div className="pilot-brand-mark" aria-hidden />
          <span className="pilot-brand-name">Cibl</span>
          <span className="pilot-brand-sep" aria-hidden />
          <span className="pilot-brand-mode">
            {mode === "pilot" ? "Pilote" : "Expert"}
          </span>
          {preview && (
            <span className="pilot-preview-chip">
              <Sparkles size={11} />
              Maquette
            </span>
          )}
        </div>

        <div className="pilot-header-meta">
          {mode === "pilot" && (
            <span className="pilot-day-chip">
              Jour {plan.dayNumber}
              <span className="pilot-day-chip-muted">· S{plan.weekNumber}</span>
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

  if (mode === "expert") {
    return (
      <div className={`pilot-expert-shell ${outfit.variable}`}>
        {header}
        <div className="pilot-expert-placeholder">
          <div className="pilot-brand-mark" style={{ width: 28, height: 28, borderRadius: 8 }} />
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
    <div className={`pilot-root ${outfit.variable}`}>
      {header}

      <div className="pilot-inner">
        <div className="pilot-greeting-block">
          <p className="pilot-kicker">Aujourd’hui</p>
          <h1 className="pilot-greeting">Bonjour {plan.userName}.</h1>
          <p className="pilot-greeting-sub">
            Ton post est prêt. {plan.contacts.length} personnes à contacter.
            <span className="pilot-greeting-rest"> C’est tout.</span>
          </p>

          <div className="pilot-week" aria-label="Objectif de la semaine">
            <div className="pilot-week-dots">
              {weekDots.map((done, i) => (
                <span
                  key={i}
                  className={`pilot-week-dot${done ? " done" : ""}`}
                  aria-label={done ? `Action ${i + 1} faite` : `Action ${i + 1} restante`}
                />
              ))}
            </div>
            <span className="pilot-week-label">
              {plan.weeklyDone}/{plan.weeklyTotal} cette semaine
            </span>
          </div>
        </div>

        <section className="pilot-section pilot-section-post" aria-labelledby="pilot-post-title">
          <div className="pilot-section-head">
            <div className="pilot-section-label" id="pilot-post-title">
              Post du jour
            </div>
            <span className="pilot-badge">{plan.post.structure}</span>
          </div>

          <article className="pilot-linkedin-feed" aria-label="Aperçu du post LinkedIn">
            <div className="pilot-linkedin-feed-header">
              <div className="pilot-linkedin-avatar" aria-hidden>
                {plan.author.avatarUrl ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={plan.author.avatarUrl} alt="" />
                ) : (
                  plan.author.initials
                )}
              </div>
              <div className="pilot-linkedin-author">
                <div className="pilot-linkedin-name">
                  {plan.author.name}
                  <span className="pilot-linkedin-you"> · Vous</span>
                </div>
                <div className="pilot-linkedin-headline">{plan.author.headline}</div>
                <div className="pilot-linkedin-meta">
                  <span>À l’instant</span>
                  <span aria-hidden> · </span>
                  <Globe size={11} strokeWidth={2} aria-label="Public" />
                </div>
              </div>
              <Linkedin size={18} className="pilot-linkedin-logo" aria-hidden />
            </div>

            <div className="pilot-linkedin-body">
              <p className="pilot-linkedin-text">
                {plan.post.hook}
                {"\n\n"}
                {plan.post.body}
              </p>
            </div>

            <div className="pilot-linkedin-reactions" aria-hidden>
              <span className="pilot-linkedin-reaction-icons">
                <span className="pilot-li-icon like" />
                <span className="pilot-li-icon celebrate" />
              </span>
              <span>Soyez le premier à réagir</span>
            </div>

            <div className="pilot-linkedin-actions" aria-hidden>
              <span><ThumbsUp size={16} strokeWidth={1.8} /> J’aime</span>
              <span><MessageCircle size={16} strokeWidth={1.8} /> Commenter</span>
              <span><Repeat2 size={16} strokeWidth={1.8} /> Republier</span>
              <span><Send size={16} strokeWidth={1.8} /> Envoyer</span>
            </div>
          </article>

          <div className="pilot-actions">
            <button
              type="button"
              className={`pilot-btn pilot-btn-primary${published ? " done" : ""}`}
              onClick={() => {
                setPublished(true);
                handleAction("Publication", onPublish);
              }}
            >
              {published ? <Check size={16} strokeWidth={2.4} /> : <Send size={16} />}
              {published ? "Publié" : "Publier"}
            </button>
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
          </div>
        </section>

        {plan.followProfiles.length > 0 && (
          <section className="pilot-section pilot-section-follow" aria-labelledby="pilot-follow-title">
            <div className="pilot-section-head">
              <div className="pilot-section-label" id="pilot-follow-title">
                <TrendingUp size={13} strokeWidth={2.2} />
                À suivre
              </div>
              <span className="pilot-section-hint">Depuis ton analyse</span>
            </div>
            <div className="pilot-follow-list">
              {plan.followProfiles.map((profile) => {
                const isFollowed = followed.has(profile.id);
                return (
                  <div key={profile.id} className="pilot-follow-row">
                    <div
                      className="pilot-avatar"
                      style={{ background: profile.accent }}
                      aria-hidden
                    >
                      {profile.initials}
                    </div>
                    <div className="pilot-follow-info">
                      <h3>{profile.name}</h3>
                      <p>{profile.reason}</p>
                    </div>
                    <button
                      type="button"
                      className={`pilot-btn pilot-btn-follow${isFollowed ? " done" : ""}`}
                      onClick={() => {
                        setFollowed((prev) => {
                          const next = new Set(prev);
                          if (next.has(profile.id)) next.delete(profile.id);
                          else next.add(profile.id);
                          return next;
                        });
                        handleAction(`Suivre ${profile.name}`, () => onFollowProfile?.(profile.id));
                      }}
                    >
                      {isFollowed ? <Check size={14} /> : <UserPlus size={14} />}
                      {isFollowed ? "Suivi" : "Suivre"}
                    </button>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        <section className="pilot-section pilot-section-contacts" aria-labelledby="pilot-contacts-title">
          <div className="pilot-section-head">
            <div className="pilot-section-label" id="pilot-contacts-title">
              <Users size={13} strokeWidth={2.2} />
              À contacter
            </div>
            <span className="pilot-section-hint">{plan.contacts.length} aujourd’hui</span>
          </div>
          <div className="pilot-contacts-list">
            {plan.contacts.map((contact) => {
              const isInvited = invited.has(contact.id);
              return (
                <article key={contact.id} className="pilot-contact-card">
                  <div className="pilot-contact-top">
                    <div
                      className="pilot-avatar"
                      style={{ background: contact.accent }}
                      aria-hidden
                    >
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
                  </div>
                  <p className="pilot-message-preview">{contact.message}</p>
                  <button
                    type="button"
                    className={`pilot-btn pilot-btn-primary pilot-btn-invite${isInvited ? " done" : ""}`}
                    onClick={() => {
                      setInvited((prev) => new Set(prev).add(contact.id));
                      handleAction(`Invitation à ${contact.name}`, () => onInvite?.(contact.id));
                    }}
                    disabled={isInvited}
                  >
                    {isInvited ? <Check size={15} /> : <UserPlus size={15} />}
                    {isInvited ? "Invitation envoyée" : "Inviter"}
                  </button>
                </article>
              );
            })}
          </div>
        </section>

        <section className="pilot-section pilot-section-strategy">
          <button
            type="button"
            className={`pilot-strategy-toggle${strategyOpen ? " open" : ""}`}
            aria-expanded={strategyOpen}
            onClick={() => setStrategyOpen((v) => !v)}
          >
            <span>
              <Target size={15} strokeWidth={2.2} />
              Ta stratégie
            </span>
            <ChevronDown size={16} className="chevron" />
          </button>
          {strategyOpen && (
            <div className="pilot-strategy-panel">
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
          )}
        </section>
      </div>

      <div className={`pilot-toast${toast ? " visible" : ""}`} role="status" aria-live="polite">
        {toast}
      </div>
    </div>
  );
}

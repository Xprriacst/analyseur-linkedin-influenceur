"use client";

import { useCallback, useMemo, useState } from "react";
import { Libre_Bodoni, Newsreader, Public_Sans } from "next/font/google";
import { Toaster, toast } from "sonner";
import {
  Check,
  ChevronDown,
  PenLine,
  RefreshCw,
  Send,
  Target,
  UserPlus,
} from "lucide-react";
import "./pilot-mode.css";

const publicSans = Public_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-pilot",
});

const libreBodoni = Libre_Bodoni({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-pilot-display",
});

const newsreader = Newsreader({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  style: ["normal", "italic"],
  variable: "--font-pilot-serif",
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

function fontVars() {
  return `${publicSans.variable} ${libreBodoni.variable} ${newsreader.variable}`;
}

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
  const [followed, setFollowed] = useState<Set<string>>(new Set());
  const [invited, setInvited] = useState<Set<string>>(new Set());
  const [published, setPublished] = useState(false);

  const edition = useMemo(
    () =>
      new Intl.DateTimeFormat("fr-FR", {
        weekday: "long",
        day: "numeric",
        month: "long",
      }).format(new Date()),
    [],
  );

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
          <span className="pilot-brand-name">Cibl</span>
          <span className="pilot-brand-mode">
            {mode === "pilot" ? "Mode pilote" : "Mode expert"}
          </span>
          {preview && <span className="pilot-preview-chip">Maquette</span>}
        </div>

        <div className="pilot-header-meta">
          {mode === "pilot" && (
            <span className="pilot-day-chip">
              Jour {plan.dayNumber}
              <span className="pilot-day-chip-muted"> / S{plan.weekNumber}</span>
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
      <div className={`pilot-expert-shell ${fontVars()}`}>
        {toaster}
        {header}
        <div className="pilot-expert-placeholder">
          <p className="pilot-kicker">App actuelle</p>
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
    <div className={`pilot-root ${fontVars()}`}>
      {toaster}
      {header}

      <div className="pilot-inner">
        <div className="pilot-masthead">
          <p className="pilot-kicker">Édition du {edition}</p>
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

        <div className="pilot-desk">
          <section className="pilot-desk-main" aria-labelledby="pilot-post-title">
            <div className="pilot-section-head">
              <div className="pilot-section-label" id="pilot-post-title">
                <span className="pilot-index">01</span>
                Post du jour
              </div>
              <span className="pilot-badge">{plan.post.structure}</span>
            </div>

            <article className="pilot-article" aria-label="Post à publier">
              <p className="pilot-article-hook">{plan.post.hook}</p>
              {postParagraphs.map((paragraph, i) => (
                <p key={i} className="pilot-article-p">
                  {paragraph}
                </p>
              ))}
              <footer className="pilot-article-byline">
                <span className="pilot-avatar" aria-hidden>
                  {plan.author.initials}
                </span>
                <div>
                  <div className="pilot-article-name">{plan.author.name}</div>
                  <div className="pilot-article-headline">{plan.author.headline}</div>
                </div>
              </footer>
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

          <aside className="pilot-desk-rail">
            {plan.followProfiles.length > 0 && (
              <section className="pilot-rail-block" aria-labelledby="pilot-follow-title">
                <div className="pilot-section-head">
                  <div className="pilot-section-label" id="pilot-follow-title">
                    <span className="pilot-index">02</span>
                    À suivre
                  </div>
                  <span className="pilot-section-hint">Depuis ton analyse</span>
                </div>
                <div className="pilot-follow-list">
                  {plan.followProfiles.map((profile) => {
                    const isFollowed = followed.has(profile.id);
                    return (
                      <div key={profile.id} className="pilot-follow-row">
                        <div className="pilot-avatar" aria-hidden>
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
                            handleAction(`Suivre ${profile.name}`, () =>
                              onFollowProfile?.(profile.id),
                            );
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

            <section className="pilot-rail-block" aria-labelledby="pilot-contacts-title">
              <div className="pilot-section-head">
                <div className="pilot-section-label" id="pilot-contacts-title">
                  <span className="pilot-index">03</span>
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
                      </div>
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
          </aside>
        </div>

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

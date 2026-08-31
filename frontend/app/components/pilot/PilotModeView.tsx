"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ChevronDown,
  Linkedin,
  PenLine,
  RefreshCw,
  Send,
  Sparkles,
  Target,
  TrendingUp,
  UserPlus,
  Users,
} from "lucide-react";
import "./pilot-mode.css";

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
  post: PilotPost;
  contacts: PilotContact[];
  strategy: PilotStrategy;
};

type InterfaceMode = "pilot" | "expert";

type PilotModeViewProps = {
  plan: PilotPlan;
  /** Affiche le bandeau « maquette » en haut de page. */
  preview?: boolean;
  /** Contrôle externe du mode (maquette avec toggle). */
  mode?: InterfaceMode;
  onModeChange?: (mode: InterfaceMode) => void;
  /** Callbacks d'action — absents = toast maquette. */
  onPublish?: () => void;
  onEditPost?: () => void;
  onRegeneratePost?: () => void;
  onInvite?: (contactId: string) => void;
};

function useTypingGreeting(fullText: string, enabled = true) {
  const [text, setText] = useState("");

  useEffect(() => {
    if (!enabled) {
      setText(fullText);
      return;
    }
    setText("");
    let i = 0;
    const id = window.setInterval(() => {
      i += 1;
      setText(fullText.slice(0, i));
      if (i >= fullText.length) window.clearInterval(id);
    }, 28);
    return () => window.clearInterval(id);
  }, [fullText, enabled]);

  return text;
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
}: PilotModeViewProps) {
  const [internalMode, setInternalMode] = useState<InterfaceMode>("pilot");
  const mode = controlledMode ?? internalMode;
  const setMode = onModeChange ?? setInternalMode;

  const [strategyOpen, setStrategyOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const greetingFull = `Bonjour ${plan.userName}, voici ton plan du jour.`;
  const greeting = useTypingGreeting(greetingFull, mode === "pilot");

  const showToast = useCallback((message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(null), 2600);
  }, []);

  const handleAction = useCallback(
    (label: string, fn?: () => void) => {
      if (fn) {
        fn();
        return;
      }
      showToast(`${label} — action simulée (maquette)`);
    },
    [showToast],
  );

  const progressPct = plan.weeklyTotal > 0
    ? Math.round((plan.weeklyDone / plan.weeklyTotal) * 100)
    : 0;

  const header = (
    <header className="pilot-header">
      <div className="pilot-brand">
        <div className="pilot-brand-mark">
          <Target size={20} strokeWidth={2.5} />
        </div>
        <div className="pilot-brand-text">
          <span className="pilot-brand-name">Cibl</span>
          <span className="pilot-brand-mode">
            <span className="pilot-brand-mode-dot" aria-hidden />
            {mode === "pilot" ? "Mode Pilote · LinkedIn" : "Mode Expert"}
          </span>
        </div>
      </div>

      <div className="pilot-header-meta">
        {mode === "pilot" && (
          <span className="pilot-day-chip">
            Jour {plan.dayNumber} · Semaine {plan.weekNumber}
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
    </header>
  );

  if (mode === "expert") {
    return (
      <div className="pilot-expert-shell">
        {preview && (
          <div className="pilot-inner" style={{ paddingBottom: 0 }}>
            <div className="pilot-preview-banner">
              <Sparkles size={14} />
              Maquette — bascule Pilote / Expert
            </div>
            {header}
          </div>
        )}
        {!preview && header}
        <div className="pilot-expert-placeholder">
          <Target size={40} strokeWidth={1.5} color="var(--primary)" />
          <h1>Mode Expert</h1>
          <p>
            Ici s&apos;affiche l&apos;application actuelle — sidebar, Contenu, Prospection, Inbox…
            Cette maquette ne reproduit pas la vue complète ; le toggle sert à valider le basculement.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="pilot-root">
      <div className="pilot-inner">
        {preview && (
          <div className="pilot-preview-banner">
            <Sparkles size={14} />
            Maquette — données fictives · LinkedIn uniquement
          </div>
        )}

        {header}

        <div className="pilot-greeting-block">
          <h1 className="pilot-greeting">
            {greeting}
            {greeting.length < greetingFull.length && (
              <span style={{ opacity: 0.5 }}>|</span>
            )}
          </h1>
          <p className="pilot-greeting-sub">
            L&apos;IA a préparé ton post et sélectionné {plan.contacts.length} personnes à contacter.
            Deux actions, c&apos;est tout pour aujourd&apos;hui.
          </p>
          <div className="pilot-progress-wrap">
            <div className="pilot-progress-label">
              <span>Objectif de la semaine</span>
              <span>
                {plan.weeklyDone}/{plan.weeklyTotal} actions
              </span>
            </div>
            <div className="pilot-progress-bar" role="progressbar" aria-valuenow={progressPct} aria-valuemin={0} aria-valuemax={100}>
              <div className="pilot-progress-fill" style={{ width: `${progressPct}%` }} />
            </div>
          </div>
        </div>

        <section className="pilot-section" aria-labelledby="pilot-post-title">
          <div className="pilot-section-label" id="pilot-post-title">
            <PenLine size={14} />
            Post du jour
          </div>
          <article className="pilot-card pilot-post-card">
            <div className="pilot-post-meta">
              <span className="pilot-badge linkedin">
                <Linkedin size={13} />
                LinkedIn
              </span>
              <span className="pilot-badge structure">{plan.post.structure}</span>
            </div>
            <div className="pilot-post-preview">
              <div className="pilot-hook">{plan.post.hook}</div>
              <p className="pilot-post-text">{plan.post.body}</p>
            </div>
            <div className="pilot-actions">
              <button
                type="button"
                className="pilot-btn pilot-btn-primary"
                onClick={() => handleAction("Publication", onPublish)}
              >
                <Send size={16} />
                Publier
              </button>
              <button
                type="button"
                className="pilot-btn pilot-btn-ghost"
                onClick={() => handleAction("Modification", onEditPost)}
              >
                <PenLine size={16} />
                Modifier
              </button>
              <button
                type="button"
                className="pilot-btn pilot-btn-ghost"
                onClick={() => handleAction("Régénération", onRegeneratePost)}
              >
                <RefreshCw size={16} />
                Autre angle
              </button>
            </div>
          </article>
        </section>

        <section className="pilot-section" aria-labelledby="pilot-contacts-title">
          <div className="pilot-section-label" id="pilot-contacts-title">
            <Users size={14} />
            {plan.contacts.length} personnes à contacter
          </div>
          <div className="pilot-contacts-grid">
            {plan.contacts.map((contact) => (
              <div key={contact.id} className="pilot-contact-card">
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
                  <span className="pilot-score">{contact.score}%</span>
                </div>
                <div className="pilot-message-preview">
                  <span>Message personnalisé</span>
                  {contact.message}
                </div>
                <button
                  type="button"
                  className="pilot-btn pilot-btn-primary"
                  onClick={() =>
                    handleAction(`Invitation à ${contact.name}`, () => onInvite?.(contact.id))
                  }
                >
                  <UserPlus size={15} />
                  Inviter
                </button>
              </div>
            ))}
          </div>
        </section>

        <section className="pilot-section">
          <button
            type="button"
            className={`pilot-strategy-toggle${strategyOpen ? " open" : ""}`}
            aria-expanded={strategyOpen}
            onClick={() => setStrategyOpen((v) => !v)}
          >
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
              <TrendingUp size={16} />
              Ta stratégie LinkedIn
            </span>
            <ChevronDown size={18} className="chevron" />
          </button>
          {strategyOpen && (
            <div className="pilot-strategy-panel">
              <ul className="pilot-strategy-list">
                <li>
                  <Target size={16} />
                  <span>
                    <strong>Cible :</strong> {plan.strategy.target}
                  </span>
                </li>
                <li>
                  <RefreshCw size={16} />
                  <span>
                    <strong>Rythme :</strong> {plan.strategy.frequency}
                  </span>
                </li>
                <li>
                  <PenLine size={16} />
                  <span>
                    <strong>Structure privilégiée :</strong> {plan.strategy.structureHint}
                  </span>
                </li>
                <li>
                  <Linkedin size={16} />
                  <span>
                    <strong>Profils à suivre :</strong>{" "}
                    {plan.strategy.profiles.join(" · ")}
                  </span>
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

"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft, ArrowRight, Bot, Check, FileText, Loader2, Send, ShieldCheck,
  Sparkles, UserPlus, X, Zap,
} from "lucide-react";

// ALE-284 — Autopilote de prospection.
//
// Jusqu'ici, contacter un lead demandait deux clics : « Inviter », puis « Envoyer le
// message » une fois l'invitation acceptée. L'autopilote déplace le consentement : le
// client répond UNE fois à trois questions, et l'app enchaîne pour lui.
//
// ⚠️ C'est la première fois que des messages partent au nom du client sans qu'il clique
// sur chaque envoi. Toute l'ergonomie de cet écran découle de là : on ne coche rien à
// sa place, la relecture est proposée par défaut, on annonce les volumes réels avant
// l'engagement, et le récapitulatif final dit en toutes lettres ce qui va se passer.

export type AutopilotTier = "green" | "orange" | "all";
export type AutopilotMessageMode = "none" | "ai" | "template";

export type AutopilotStep = {
  key: "invite" | "compose" | "send";
  label: string;
  detail: string;
  active: boolean;
  awaits_user?: boolean;
};

export type AutopilotState = {
  enabled: boolean;
  tier: AutopilotTier;
  invite_min_score: number;
  invite_daily_cap: number;
  message_mode: AutopilotMessageMode;
  message_template: string;
  requires_validation: boolean;
  steps: AutopilotStep[];
};

export type LeadTierCounts = { green: number; orange: number; red: number; unscored: number };

const STEP_ICONS = { invite: UserPlus, compose: Bot, send: Send } as const;

/** Schéma de séquence — le rappel permanent de « comment mon autopilote tourne ».
 *
 *  ⚠️ Les étapes viennent du SERVEUR (`automation.steps`), calculées par le même module
 *  que le planificateur. On ne les reconstruit jamais ici : un schéma qui annoncerait
 *  « tu relis avant envoi » alors que les messages partent seuls serait le pire bug
 *  possible de cet écran. Ce composant ne fait que les peindre. */
export function AutopilotSequence({
  steps,
  enabled,
  compact = false,
}: {
  steps: AutopilotStep[];
  enabled: boolean;
  compact?: boolean;
}) {
  return (
    <div
      style={{ display: "flex", alignItems: "stretch", gap: compact ? 6 : 8, flexWrap: "wrap" }}
      role="list"
      aria-label="Étapes de ton autopilote"
    >
      {steps.map((step, idx) => {
        const Icon = STEP_ICONS[step.key] || Sparkles;
        const on = step.active && enabled;
        // Trois états visuels, pas deux : « éteinte », « active » et « active mais elle
        // t'attend ». Sans le troisième, « je relis avant envoi » et « ça part tout
        // seul » auraient exactement la même apparence — la distinction qui compte le
        // plus pour le client serait justement celle qu'on ne montrerait pas.
        const awaiting = on && !!step.awaits_user;
        return (
          <div key={step.key} style={{ display: "flex", alignItems: "center", gap: compact ? 6 : 8 }} role="listitem">
            <div
              title={`${step.label} — ${step.detail}`}
              style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: compact ? "6px 10px" : "8px 12px",
                borderRadius: 10,
                border: `1px ${awaiting ? "dashed" : "solid"} ${on ? "var(--success)" : "var(--border)"}`,
                background: on ? "color-mix(in srgb, var(--success) 10%, transparent)" : "transparent",
                opacity: on ? 1 : 0.45,
                minWidth: 0,
              }}
            >
              <Icon size={compact ? 14 : 15} style={{ flexShrink: 0, color: on ? "var(--success)" : "var(--muted)" }} />
              <div style={{ display: "grid", minWidth: 0 }}>
                <span style={{ fontSize: compact ? 12 : 12.5, fontWeight: 600, whiteSpace: "nowrap" }}>
                  {step.label}
                </span>
                {!compact && (
                  <span style={{ fontSize: 11, color: "var(--muted)", whiteSpace: "nowrap" }}>
                    {step.detail}
                  </span>
                )}
              </div>
            </div>
            {idx < steps.length - 1 && (
              <ArrowRight size={13} style={{ color: "var(--muted)", opacity: 0.5, flexShrink: 0 }} aria-hidden />
            )}
          </div>
        );
      })}
    </div>
  );
}

type Choice = {
  value: string;
  title: string;
  detail: string;
  meta?: string;
  recommended?: boolean;
};

/** Carte de choix cliquable (un vrai bouton : navigable au clavier, état annoncé). */
function ChoiceCard({
  choice, selected, onSelect, disabled,
}: {
  choice: Choice; selected: boolean; onSelect: () => void; disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={disabled}
      aria-pressed={selected}
      style={{
        display: "grid", gap: 3, textAlign: "left", width: "100%",
        padding: "12px 14px", borderRadius: 10, cursor: disabled ? "not-allowed" : "pointer",
        border: `1px solid ${selected ? "var(--primary)" : "var(--border)"}`,
        outline: selected ? "2px solid color-mix(in srgb, var(--primary) 35%, transparent)" : "none",
        background: selected ? "color-mix(in srgb, var(--primary) 8%, transparent)" : "transparent",
        font: "inherit", color: "inherit", opacity: disabled ? 0.5 : 1,
      }}
    >
      <span style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13.5, fontWeight: 600 }}>
        {selected && <Check size={14} style={{ color: "var(--primary)", flexShrink: 0 }} />}
        {choice.title}
        {choice.recommended && (
          <span style={{
            fontSize: 10.5, fontWeight: 700, letterSpacing: 0.3, padding: "2px 6px", borderRadius: 5,
            background: "color-mix(in srgb, var(--success) 18%, transparent)", color: "var(--success)",
          }}>
            RECOMMANDÉ
          </span>
        )}
      </span>
      <span style={{ fontSize: 12.5, color: "var(--muted)" }}>{choice.detail}</span>
      {choice.meta && <span style={{ fontSize: 12, fontWeight: 600 }}>{choice.meta}</span>}
    </button>
  );
}

const TOTAL_STEPS = 4;

export default function AutopilotModal({
  state,
  counts,
  busy = false,
  error = "",
  onSave,
  onClose,
}: {
  state: AutopilotState;
  counts: LeadTierCounts | null;
  busy?: boolean;
  error?: string;
  /** Retourne `true` si le serveur a bien enregistré : la pop-up ne se ferme que dans
   *  ce cas, pour qu'on ne reparte jamais convaincu d'avoir armé une séquence refusée. */
  onSave: (patch: Record<string, unknown>) => Promise<boolean>;
  onClose: () => void;
}) {
  const [step, setStep] = useState(1);
  const [tier, setTier] = useState<AutopilotTier>(state.tier);
  const [mode, setMode] = useState<AutopilotMessageMode>(state.message_mode);
  const [template, setTemplate] = useState(state.message_template || "");
  const [review, setReview] = useState(state.requires_validation);

  // Le mode template n'a de sens qu'avec un texte : on n'autorise pas à avancer sans.
  const templateReady = mode !== "template" || template.trim().length > 0;
  const sendsMessage = mode !== "none";

  // Le conseil dépend de ce que le client vient de choisir, et il n'est pas cosmétique :
  // un message d'IA est différent pour chaque personne (donc imprévisible → à relire),
  // un template est un texte qu'il a écrit lui-même et déjà vu (donc sûr → il peut
  // partir seul). Recommander la même chose dans les deux cas serait un conseil vide.
  const recommendReview = mode === "ai";

  // Quand il n'y a pas de message, la question de la relecture ne se pose pas : on
  // remet la valeur par défaut au lieu de laisser traîner un réglage sans objet.
  useEffect(() => { if (!sendsMessage) setReview(true); }, [sendsMessage]);
  // Changer de mode change le bon défaut de relecture, tant que le client n'est pas
  // arrivé sur la question.
  useEffect(() => { if (step < 3) setReview(mode === "ai"); }, [mode, step]);

  const tierChoices: Choice[] = useMemo(() => {
    const n = (v: number | undefined) => (counts ? `${v ?? 0} lead${(v ?? 0) > 1 ? "s" : ""} concerné${(v ?? 0) > 1 ? "s" : ""}` : undefined);
    const green = counts?.green ?? 0;
    const orange = counts?.orange ?? 0;
    const red = counts?.red ?? 0;
    return [
      {
        value: "green",
        title: "🟢 Uniquement mes leads verts",
        detail: "Ceux qui correspondent vraiment à ton client idéal.",
        meta: n(green),
        recommended: true,
      },
      {
        value: "orange",
        title: "🟢🟠 Verts et orange",
        detail: "Tu élargis aux profils plausibles, à creuser.",
        meta: n(green + orange),
      },
      {
        value: "all",
        title: "🟢🟠🔴 Tous mes leads",
        detail: "Y compris ceux qui sont hors de ta cible. Plus de volume, mais un taux d'acceptation plus faible — et c'est ce taux qui protège ton compte.",
        meta: n(green + orange + red),
      },
    ];
  }, [counts]);

  async function activate() {
    const ok = await onSave({
      auto_prospection_enabled: true,
      auto_invite_tier: tier,
      auto_message_mode: mode,
      auto_message_template: mode === "template" ? template.trim() : template.trim() || null,
      auto_message_requires_validation: sendsMessage ? review : true,
    });
    if (ok) onClose();
  }

  async function turnOff() {
    const ok = await onSave({ auto_prospection_enabled: false });
    if (ok) onClose();
  }

  const canContinue =
    (step === 1) ||
    (step === 2 && templateReady) ||
    (step === 3) ||
    step === 4;

  // Aperçu du schéma pendant le réglage. Il ne peut pas venir du serveur (rien n'est
  // encore enregistré), donc il est reconstruit ici — mais UNIQUEMENT pour l'étape de
  // récapitulatif, où il décrit le choix en cours. Le schéma qui fait foi, celui de
  // l'écran Prospection, reste celui du serveur.
  const previewSteps: AutopilotStep[] = [
    {
      key: "invite",
      label: "Demande de connexion",
      detail: tier === "green" ? "Aux leads verts" : tier === "orange" ? "Aux leads verts et orange" : "À tous les leads",
      active: true,
    },
    {
      key: "compose",
      label: "Premier message",
      detail: mode === "ai" ? "Rédigé par l'IA pour chaque lead" : mode === "template" ? "Ton template, personnalisé" : "Aucun message prévu",
      active: sendsMessage,
    },
    {
      key: "send",
      label: "Envoi du message",
      detail: !sendsMessage ? "Aucun message prévu" : review ? "Après ta relecture" : "Envoi sans relecture",
      active: sendsMessage,
      awaits_user: sendsMessage && review,
    },
  ];

  return (
    <div
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 1000,
        display: "flex", alignItems: "center", justifyContent: "center", padding: 16,
      }}
      onClick={() => { if (!busy) onClose(); }}
    >
      <div
        className="card"
        style={{ maxWidth: 620, width: "100%", padding: 24, maxHeight: "90vh", overflowY: "auto" }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Réglages de l'autopilote"
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
          <Zap size={18} style={{ color: "var(--primary)" }} />
          <h3 style={{ margin: 0, flex: 1 }}>Autopilote</h3>
          <span style={{ fontSize: 12, color: "var(--muted)" }}>Étape {step} sur {TOTAL_STEPS}</span>
          <button
            type="button" onClick={onClose} disabled={busy} aria-label="Fermer"
            style={{ background: "none", border: "none", cursor: "pointer", color: "var(--muted)", padding: 4 }}
          >
            <X size={16} />
          </button>
        </div>

        <div style={{ height: 3, background: "var(--border)", borderRadius: 2, margin: "10px 0 18px" }}>
          <div style={{ height: "100%", width: `${(step / TOTAL_STEPS) * 100}%`, background: "var(--primary)", borderRadius: 2, transition: "width .2s" }} />
        </div>

        {/* ── 1. À qui ─────────────────────────────────────────────────────── */}
        {step === 1 && (
          <div style={{ display: "grid", gap: 10 }}>
            <h4 style={{ margin: 0, fontSize: 15 }}>À qui l&apos;autopilote envoie-t-il des demandes de connexion ?</h4>
            <p style={{ margin: "0 0 4px", fontSize: 12.5, color: "var(--muted)" }}>
              Chaque lead est noté sur 100 selon ton ciblage — c&apos;est la pastille de couleur que tu vois
              dans ta liste. Les leads que tu as écartés à la main ne sont jamais contactés.
            </p>
            {tierChoices.map((c) => (
              <ChoiceCard
                key={c.value} choice={c} selected={tier === c.value}
                onSelect={() => setTier(c.value as AutopilotTier)} disabled={busy}
              />
            ))}
            {counts && counts.unscored > 0 && (
              <p style={{ margin: 0, fontSize: 12, color: "var(--muted)" }}>
                {counts.unscored} lead{counts.unscored > 1 ? "s ne sont pas encore notés" : " n'est pas encore noté"} :
                l&apos;autopilote ne {counts.unscored > 1 ? "les" : "le"} contactera pas tant qu&apos;on ne sait pas
                {counts.unscored > 1 ? " s'ils correspondent" : " s'il correspond"} à ta cible.
              </p>
            )}
          </div>
        )}

        {/* ── 2. Quel message ──────────────────────────────────────────────── */}
        {step === 2 && (
          <div style={{ display: "grid", gap: 10 }}>
            <h4 style={{ margin: 0, fontSize: 15 }}>Que veux-tu envoyer une fois l&apos;invitation acceptée ?</h4>
            <p style={{ margin: "0 0 4px", fontSize: 12.5, color: "var(--muted)" }}>
              Le message part quelques heures après l&apos;acceptation, jamais dans la seconde.
            </p>
            <ChoiceCard
              choice={{
                value: "ai",
                title: "Un message rédigé par l'IA",
                detail: "Écrit pour chaque personne à partir de son commentaire, de son poste et de ton ciblage. Chaque message est différent.",
                recommended: true,
              }}
              selected={mode === "ai"} onSelect={() => setMode("ai")} disabled={busy}
            />
            <ChoiceCard
              choice={{
                value: "template",
                title: "Mon propre message type",
                detail: "Le même texte pour tout le monde, avec le prénom et le poste insérés automatiquement.",
              }}
              selected={mode === "template"} onSelect={() => setMode("template")} disabled={busy}
            />
            {mode === "template" && (
              <div style={{ display: "grid", gap: 6, paddingLeft: 14, borderLeft: "2px solid var(--border)" }}>
                <textarea
                  value={template}
                  onChange={(e) => setTemplate(e.target.value)}
                  rows={5}
                  disabled={busy}
                  placeholder={"Bonjour {{prenom}}, j'ai vu ton commentaire sur le post de… et ton poste de {{titre}} m'a interpellé.\n\nOn échange ?"}
                  style={{ width: "100%", boxSizing: "border-box", padding: 10, fontSize: 13, resize: "vertical" }}
                />
                <p style={{ margin: 0, fontSize: 12, color: "var(--muted)" }}>
                  Variables disponibles : <code>{"{{prenom}}"}</code> <code>{"{{nom}}"}</code> <code>{"{{titre}}"}</code>.
                  Si l&apos;information manque pour une personne, la variable est simplement retirée du texte —
                  elle ne partira jamais telle quelle.
                </p>
                {!templateReady && (
                  <p style={{ margin: 0, fontSize: 12, color: "var(--warning, #b8860b)" }}>
                    Écris ton message pour pouvoir continuer.
                  </p>
                )}
              </div>
            )}
            <ChoiceCard
              choice={{
                value: "none",
                title: "Aucun message",
                detail: "L'autopilote se contente d'envoyer les demandes de connexion. Tu écris toi-même à ceux qui acceptent.",
              }}
              selected={mode === "none"} onSelect={() => setMode("none")} disabled={busy}
            />
          </div>
        )}

        {/* ── 3. Relecture ─────────────────────────────────────────────────── */}
        {step === 3 && (
          <div style={{ display: "grid", gap: 10 }}>
            {sendsMessage ? (
              <>
                <h4 style={{ margin: 0, fontSize: 15 }}>Veux-tu relire chaque message avant qu&apos;il parte ?</h4>
                <p style={{ margin: "0 0 4px", fontSize: 12.5, color: "var(--muted)" }}>
                  {recommendReview
                    ? "L'IA écrit un message différent pour chaque personne : tu ne peux pas savoir à l'avance ce qu'elle dira. Commence par relire — tu pourras passer en automatique quand tu auras confiance."
                    : "Ton message type est un texte que tu as écrit toi-même et que tu as déjà sous les yeux : il n'y a pas de surprise à attendre, il peut partir seul."}
                </p>
                <ChoiceCard
                  choice={{
                    value: "review",
                    title: "Je relis chaque message",
                    detail: "Les messages s'accumulent dans « À valider » sur cette page. Rien ne part tant que tu n'as pas dit oui.",
                    recommended: recommendReview,
                  }}
                  selected={review} onSelect={() => setReview(true)} disabled={busy}
                />
                <ChoiceCard
                  choice={{
                    value: "auto",
                    title: "Envoi automatique",
                    detail: "Les messages partent seuls, au rythme de sécurité. Tu les retrouves dans ton Inbox après coup.",
                    recommended: !recommendReview,
                  }}
                  selected={!review} onSelect={() => setReview(false)} disabled={busy}
                />
              </>
            ) : (
              <>
                <h4 style={{ margin: 0, fontSize: 15 }}>Rien à relire</h4>
                <p style={{ margin: 0, fontSize: 13, color: "var(--muted)" }}>
                  Tu as choisi de n&apos;envoyer aucun message : l&apos;autopilote se limite aux demandes de
                  connexion. Il n&apos;y a donc rien à valider.
                </p>
              </>
            )}
          </div>
        )}

        {/* ── 4. Récapitulatif ─────────────────────────────────────────────── */}
        {step === 4 && (
          <div style={{ display: "grid", gap: 14 }}>
            <h4 style={{ margin: 0, fontSize: 15 }}>Voici ce que ton autopilote va faire</h4>
            <AutopilotSequence steps={previewSteps} enabled />
            <div style={{ display: "grid", gap: 6, fontSize: 12.5, color: "var(--muted)" }}>
              <span>
                <ShieldCheck size={13} style={{ verticalAlign: -2, marginRight: 6, color: "var(--success)" }} />
                Tout passe par ton rythme de sécurité : plage horaire, jours ouvrés, montée en puissance
                progressive et plafonds. L&apos;autopilote ne peut pas les dépasser.
              </span>
              <span>
                <ShieldCheck size={13} style={{ verticalAlign: -2, marginRight: 6, color: "var(--success)" }} />
                Au maximum {state.invite_daily_cap} demandes de connexion déposées par jour.
              </span>
              <span>
                <ShieldCheck size={13} style={{ verticalAlign: -2, marginRight: 6, color: "var(--success)" }} />
                Tu peux le couper à tout moment, et continuer à inviter qui tu veux à la main.
              </span>
            </div>
            {sendsMessage && !review && (
              // On ne masque pas ce que le client vient d'accepter : c'est le seul écran
              // où il donne son accord pour des envois qu'il ne verra pas passer.
              <p style={{
                margin: 0, fontSize: 12.5, padding: "10px 12px", borderRadius: 8,
                background: "color-mix(in srgb, var(--warning, #b8860b) 12%, transparent)",
              }}>
                Des messages partiront en ton nom sans que tu les relises.
              </p>
            )}
          </div>
        )}

        {error && <div className="error" style={{ marginTop: 14, fontSize: 13 }}>{error}</div>}

        <div style={{ display: "flex", gap: 8, justifyContent: "space-between", alignItems: "center", marginTop: 20 }}>
          <div>
            {state.enabled && step === 1 && (
              <button type="button" className="secondary-button" onClick={turnOff} disabled={busy} style={{ fontSize: 13 }}>
                Désactiver l&apos;autopilote
              </button>
            )}
            {step > 1 && (
              <button type="button" className="secondary-button" onClick={() => setStep((s) => s - 1)} disabled={busy} style={{ fontSize: 13 }}>
                <ArrowLeft size={13} /> Retour
              </button>
            )}
          </div>
          {step < TOTAL_STEPS ? (
            <button
              type="button" className="primary-button" disabled={busy || !canContinue}
              onClick={() => setStep((s) => s + 1)}
            >
              Continuer <ArrowRight size={14} />
            </button>
          ) : (
            <button type="button" className="primary-button" onClick={activate} disabled={busy}>
              {busy ? <><Loader2 size={14} className="spinning" /> Activation…</> : <><Zap size={14} /> Activer l&apos;autopilote</>}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/** Bandeau « À valider » : les messages que l'autopilote a rédigés et qui attendent
 *  le feu vert du client. Éditable avant validation — ce qui part est exactement ce
 *  qui est à l'écran au moment du clic. */
export function AutopilotDrafts({
  drafts,
  onApprove,
  onReject,
}: {
  drafts: Array<{ id: string; body?: string | null; leads?: { name?: string | null; headline?: string | null; score?: number | null } | null }>;
  onApprove: (id: string, text: string) => Promise<boolean>;
  onReject: (id: string) => Promise<boolean>;
}) {
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState<string | null>(null);

  if (!drafts.length) return null;

  return (
    <div className="card" style={{ marginBottom: 16, padding: 16, display: "grid", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <FileText size={16} style={{ color: "var(--primary)" }} />
        <strong style={{ fontSize: 14 }}>À valider — {drafts.length} message{drafts.length > 1 ? "s" : ""}</strong>
        <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
          rédigé{drafts.length > 1 ? "s" : ""} par ton autopilote. Rien ne part tant que tu n&apos;as pas validé.
        </span>
      </div>
      {drafts.map((d) => {
        const text = edits[d.id] ?? (d.body || "");
        const busy = busyId === d.id;
        return (
          <div key={d.id} style={{ display: "grid", gap: 8, padding: 12, border: "1px solid var(--border)", borderRadius: 10 }}>
            <div style={{ fontSize: 13, fontWeight: 600 }}>
              {d.leads?.name || "Ce lead"}
              {d.leads?.headline && (
                <span style={{ fontWeight: 400, color: "var(--muted)" }}> — {d.leads.headline}</span>
              )}
            </div>
            <textarea
              value={text}
              onChange={(e) => setEdits((m) => ({ ...m, [d.id]: e.target.value }))}
              rows={4}
              disabled={busy}
              style={{ width: "100%", boxSizing: "border-box", padding: 10, fontSize: 13, resize: "vertical" }}
            />
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button
                type="button" className="secondary-button" disabled={busy} style={{ fontSize: 13 }}
                onClick={async () => { setBusyId(d.id); await onReject(d.id); setBusyId(null); }}
              >
                <X size={13} /> Ne pas envoyer
              </button>
              <button
                type="button" className="primary-button" disabled={busy || !text.trim()} style={{ fontSize: 13 }}
                onClick={async () => { setBusyId(d.id); await onApprove(d.id, text); setBusyId(null); }}
              >
                {busy ? <Loader2 size={13} className="spinning" /> : <Check size={13} />} Valider l&apos;envoi
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

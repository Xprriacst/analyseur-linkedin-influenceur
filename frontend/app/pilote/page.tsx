"use client";

/**
 * Landing `/pilote` — écran d'entrée du mode Pilote gratuit.
 *
 * Structure Freelance Mention (argument + preuve à gauche, compte à droite),
 * DA du Mode Pilote (encre + aurore). Le formulaire est sur le premier écran
 * parce que le funnel mesure vue → compte créé : le cacher derrière un scroll
 * viderait le compteur.
 *
 * ⚠️ Deux lignes qui FONT le compteur (ticket Funnel /pilote) :
 *   `trackPilotePageView()` au montage
 *   `piloteSignupMetadata()` dans `signUp`
 * Sans elles, POST /pilote/page-view n'est jamais appelé et aucun compte
 * n'est tagué `landing: pilote`.
 *
 * Google OAuth : pas de bouton. Cibl n'a aujourd'hui que e-mail + mot de passe
 * (aucun OAuth, aucun magic link). Un bouton « Continuer avec Google » serait
 * mort — Alex tranchera s'il faut l'ouvrir.
 *
 * Groupe Skool : annoncé à gauche (copy, pas de lien). Le lien d'invitation
 * n'arrive qu'APRÈS inscription, via `GET /pilote/invite` authentifié.
 * Variable absente ⇒ pas de bouton.
 */

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Instrument_Serif } from "next/font/google";
import { ArrowRight, Check, Loader2, Users } from "lucide-react";
import { supabase, authHeaders } from "../lib/supabase";
import { trackPilotePageView, piloteSignupMetadata } from "../lib/funnel";
import { CLIENT_TESTIMONIALS, PROOF_INFLUENCERS_ANALYZED, PROOF_POSTS_ANALYZED } from "../lib/founders";
import {
  PILOTE_CONTACTS_PER_DAY,
  PILOTE_GROUP_BLURB,
  PILOTE_POSTS_PER_DAY,
} from "../lib/pilote";
import "./pilote-landing.css";

const serif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  style: "italic",
  variable: "--font-pilote-serif",
});

const DIRECT_API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "https://analyseur-linkedin-influenceur-api-eu.onrender.com";

type Mode = "signup" | "signin";
type Phase = "form" | "success";

export default function PilotePage() {
  const router = useRouter();
  const stayOnSuccess = useRef(false);
  const [mode, setMode] = useState<Mode>("signup");
  const [phase, setPhase] = useState<Phase>("form");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const password2Ref = useRef<HTMLInputElement>(null);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(false);
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);

  useEffect(() => {
    trackPilotePageView();
  }, []);

  useEffect(() => {
    (async () => {
      const { data } = await supabase.auth.getSession();
      // Re-vérifié APRÈS l'await : un signup peut avoir abouti pendant que
      // getSession était en vol. Sans ça on enverrait le nouvel inscrit sur
      // `/` avant l'écran de succès (donc sans le lien Skool).
      if (stayOnSuccess.current) return;
      if (data.session) router.replace("/");
    })();
  }, [router]);

  const passwordMismatch = mode === "signup" && password2.length > 0 && password !== password2;

  async function loadInvite() {
    try {
      const res = await fetch(`${DIRECT_API_URL}/pilote/invite`, {
        headers: await authHeaders(),
      });
      if (!res.ok) return;
      const data = await res.json();
      const url = typeof data?.url === "string" && data.url.startsWith("https://") ? data.url : null;
      setInviteUrl(url);
    } catch {
      /* pas de bouton — mieux qu'un lien mort */
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setInfo("");
    if (mode === "signup" && password !== password2) {
      password2Ref.current?.focus();
      return;
    }
    setLoading(true);
    try {
      if (mode === "signin") {
        const { error: err } = await supabase.auth.signInWithPassword({ email, password });
        if (err) throw err;
        router.push("/");
        return;
      }

      const { data, error: err } = await supabase.auth.signUp({
        email,
        password,
        options: {
          data: piloteSignupMetadata({ onboarding_pending: true, onboarding_done: false }),
        },
      });
      if (err) throw err;

      if (data.session) {
        stayOnSuccess.current = true;
        await loadInvite();
        setPhase("success");
        setLoading(false);
        return;
      }

      setInfo("Compte créé. Confirme ton e-mail, puis reconnecte-toi ici pour entrer dans le mode Pilote.");
      setMode("signin");
      setLoading(false);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Une erreur est survenue.";
      if (/already registered|already been registered|user already exists/i.test(msg)) {
        setMode("signin");
        setError("Tu as déjà un compte avec cet e-mail. Connecte-toi.");
      } else {
        setError(msg);
      }
      setLoading(false);
    }
  }

  return (
    <div className={`pilote-root ${serif.variable}`}>
      <section className="pilote-proof" aria-label="Ce que tu obtiens">
        <div className="pilote-aurora" aria-hidden="true">
          <span className="pilote-orb pilote-orb-a" />
          <span className="pilote-orb pilote-orb-b" />
          <span className="pilote-orb pilote-orb-c" />
        </div>
        <div className="pilote-proof-inner">
          <div className="pilote-brand">
            <span className="pilote-brand-mark" aria-hidden="true" />
            Cibl
            <span className="pilote-brand-beta">Pilote</span>
          </div>

          <p className="pilote-kicker">Pour les freelances IA</p>
          <h1 className="pilote-h1">
            Le <em className="pilote-em">rythme</em> pour trouver tes missions sans scroller LinkedIn.
          </h1>
          <p className="pilote-lead">
            {PILOTE_POSTS_PER_DAY} post par jour. Jusqu&apos;à {PILOTE_CONTACTS_PER_DAY} contacts.
            Un {PILOTE_GROUP_BLURB}. Gratuit, sans carte — tu commences tout de suite.
          </p>

          <ul className="pilote-pills">
            <li>
              <Check size={16} aria-hidden="true" />
              {PILOTE_POSTS_PER_DAY} post LinkedIn écrit pour toi, chaque jour
            </li>
            <li>
              <Check size={16} aria-hidden="true" />
              Jusqu&apos;à {PILOTE_CONTACTS_PER_DAY} contacts à relancer, déjà triés
            </li>
            <li>
              <Users size={16} aria-hidden="true" />
              Accès au {PILOTE_GROUP_BLURB}
            </li>
          </ul>

          <div className="pilote-trust">
            <span>Sans carte bancaire</span>
            <span>Tu commences sans connecter LinkedIn</span>
            <span>Cadençage : horaires, jours ouvrés, warm-up</span>
          </div>

          <ul className="pilote-quotes">
            {CLIENT_TESTIMONIALS.map((t) => (
              <li key={t.name}>
                <blockquote className="pilote-quote">
                  <p>«&nbsp;{t.quote}&nbsp;»</p>
                  <footer>{t.name}</footer>
                </blockquote>
              </li>
            ))}
          </ul>

          <p className="pilote-teaser">
            Le mode Expert (analyse, veille, volumes) s&apos;ouvre quand tu es prêt — tu le vois
            grisé dans l&apos;app, rien n&apos;est caché.
          </p>
          <p className="pilote-proof-foot">
            {PROOF_INFLUENCERS_ANALYZED}+ influenceurs analysés · {PROOF_POSTS_ANALYZED.toLocaleString("fr-FR")}+ posts
            décortiqués
          </p>
        </div>
      </section>

      <section className="pilote-form-pane">
        <div className="pilote-form-card">
          {phase === "success" ? (
            <div className="pilote-success">
              <h1>Compte créé</h1>
              <p className="pilote-sub">
                On prépare ton premier post et tes {PILOTE_CONTACTS_PER_DAY} contacts. Ça se passe dans l&apos;app.
              </p>
              {inviteUrl && (
                <div className="pilote-invite">
                  <p>
                    Rejoins le {PILOTE_GROUP_BLURB} — un cercle de freelances, pas une communauté produit.
                  </p>
                  <a
                    className="pilote-invite-btn"
                    href={inviteUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    data-testid="pilote-skool-invite"
                  >
                    Rejoindre le groupe privé
                    <ArrowRight size={16} aria-hidden="true" />
                  </a>
                </div>
              )}
              <button type="button" className="pilote-submit" onClick={() => router.push("/")}>
                Entrer dans Cibl
                <ArrowRight size={16} aria-hidden="true" />
              </button>
            </div>
          ) : (
            <form onSubmit={submit}>
              <h1>{mode === "signup" ? "Crée ton compte" : "Connexion"}</h1>
              <p className="pilote-sub">
                {mode === "signup"
                  ? "Gratuit, sans carte. Tu confirmes le mot de passe : tu es dans l'app tout de suite."
                  : "Connecte-toi à ton compte."}
              </p>

              <label htmlFor="pilote-email">Email</label>
              <input
                id="pilote-email"
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="toi@email.com"
              />

              <label htmlFor="pilote-password">Mot de passe</label>
              <input
                id="pilote-password"
                type="password"
                required
                minLength={6}
                autoComplete={mode === "signup" ? "new-password" : "current-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
              />

              {mode === "signup" && (
                <>
                  <label htmlFor="pilote-password2">Confirme ton mot de passe</label>
                  <input
                    id="pilote-password2"
                    ref={password2Ref}
                    type="password"
                    required
                    minLength={6}
                    autoComplete="new-password"
                    value={password2}
                    onChange={(e) => setPassword2(e.target.value)}
                    placeholder="Retape ton mot de passe"
                  />
                  {passwordMismatch && (
                    <p className="pilote-field-error">Les deux mots de passe ne sont pas identiques.</p>
                  )}
                </>
              )}

              {error && <div className="pilote-error">{error}</div>}
              {info && <div className="pilote-info">{info}</div>}

              <button className="pilote-submit" type="submit" disabled={loading}>
                {loading ? (
                  <Loader2 className="spin" size={16} />
                ) : mode === "signup" ? (
                  <>
                    Commencer gratuitement
                    <ArrowRight size={16} aria-hidden="true" />
                  </>
                ) : (
                  "Se connecter"
                )}
              </button>

              <button
                type="button"
                className="pilote-switch"
                onClick={() => {
                  setMode(mode === "signin" ? "signup" : "signin");
                  setError("");
                  setInfo("");
                }}
              >
                {mode === "signin" ? (
                  <>
                    Pas encore de compte ? <b>Créer un compte</b>
                  </>
                ) : (
                  <>
                    Déjà un compte ? <b>Se connecter</b>
                  </>
                )}
              </button>
              {mode === "signup" && (
                <p className="pilote-legal">Sans carte. L&apos;envoi LinkedIn se relie plus tard, cadencé.</p>
              )}
            </form>
          )}
        </div>
      </section>
    </div>
  );
}

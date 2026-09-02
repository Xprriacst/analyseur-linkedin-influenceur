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
 * Google : `signInWithOAuth({ provider: "google" })`, retour sur
 * `/pilote?oauth=google`. Le tag `landing: pilote` passe par `updateUser`
 * (OAuth n'accepte pas `options.data`). Un compte déjà existant qui se
 * reconnecte va directement dans l'app.
 *
 * Groupe Skool : annoncé à gauche (copy, pas de lien). Le bouton
 * « Rejoindre le groupe privé » n'existe que sur l'écran « Compte créé »,
 * après inscription, et seulement si `GET /pilote/invite` renvoie une URL https.
 */

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Instrument_Serif } from "next/font/google";
import { ArrowRight, Check, Loader2, Users } from "lucide-react";
import { supabase, authHeaders } from "../lib/supabase";
import { PILOTE_LANDING, trackPilotePageView, piloteSignupMetadata } from "../lib/funnel";
import {
  CLIENT_TESTIMONIALS,
  PROOF_INFLUENCERS_ANALYZED,
  PROOF_POSTS_ANALYZED,
} from "../lib/founders";
import {
  PILOTE_CONTACTS_PER_DAY,
  PILOTE_GROUP_BLURB,
  PILOTE_POSTS_PER_DAY,
  isFreshAccount,
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
    const fromGoogle = () =>
      new URLSearchParams(window.location.search).get("oauth") === "google";

    async function onSession(user: { created_at: string; user_metadata?: Record<string, unknown> } | null) {
      if (stayOnSuccess.current) return;
      if (!user) return;
      if (fromGoogle() && isFreshAccount(user.created_at)) {
        stayOnSuccess.current = true;
        if (user.user_metadata?.landing !== PILOTE_LANDING) {
          await supabase.auth.updateUser({
            data: piloteSignupMetadata({ onboarding_pending: true, onboarding_done: false }),
          });
        }
        await loadInvite();
        setPhase("success");
        window.history.replaceState({}, "", "/pilote");
        return;
      }
      router.replace("/");
    }

    let cancelled = false;
    (async () => {
      const { data } = await supabase.auth.getSession();
      if (cancelled) return;
      await onSession(data.session?.user ?? null);
    })();
    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => {
      if (cancelled) return;
      void onSession(session?.user ?? null);
    });
    return () => {
      cancelled = true;
      sub.subscription.unsubscribe();
    };
  }, [router]);

  const passwordMismatch = mode === "signup" && password2.length > 0 && password !== password2;

  async function continueWithGoogle() {
    setError("");
    setInfo("");
    setLoading(true);
    try {
      const { error: err } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: {
          redirectTo: `${window.location.origin}/pilote?oauth=google`,
          queryParams: { prompt: "select_account" },
        },
      });
      if (err) throw err;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Connexion Google impossible.";
      setError(msg);
      setLoading(false);
    }
  }

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

      stayOnSuccess.current = true;
      const { data, error: err } = await supabase.auth.signUp({
        email,
        password,
        options: {
          data: piloteSignupMetadata({ onboarding_pending: true, onboarding_done: false }),
        },
      });
      if (err) {
        stayOnSuccess.current = false;
        throw err;
      }

      if (data.session) {
        stayOnSuccess.current = true;
        await loadInvite();
        setPhase("success");
        setLoading(false);
        return;
      }

      setInfo("Compte créé. Confirme ton e-mail, puis reconnecte-toi ici pour entrer dans le mode Pilote.");
      stayOnSuccess.current = false;
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
                  ? "Gratuit, sans carte. Google ou e-mail : tu es dans l'app tout de suite."
                  : "Connecte-toi à ton compte."}
              </p>

              <button
                type="button"
                className="pilote-google"
                onClick={continueWithGoogle}
                disabled={loading}
                data-testid="pilote-google"
              >
                <GoogleMark />
                Continuer avec Google
              </button>
              <p className="pilote-divider" role="separator">
                ou
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

function GoogleMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path
        fill="#FFC107"
        d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.3 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 8 3.1l5.7-5.7C34.2 6.1 29.4 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.3-.4-3.5z"
      />
      <path
        fill="#FF3D00"
        d="M6.3 14.7 12.9 19.6C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 8 3.1l5.7-5.7C34.2 6.1 29.4 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"
      />
      <path
        fill="#4CAF50"
        d="M24 44c5.2 0 10-2 13.6-5.2l-6.3-5.3C29.3 35.1 26.8 36 24 36c-5.3 0-9.7-3.3-11.3-7.9l-6.5 5C9.6 39.6 16.3 44 24 44z"
      />
      <path
        fill="#1976D2"
        d="M43.6 20.5H42V20H24v8h11.3c-1.1 3.2-3.5 5.8-6.7 7.5l.1-.1 6.3 5.3C36.9 41.9 44 37 44 24c0-1.3-.1-2.3-.4-3.5z"
      />
    </svg>
  );
}

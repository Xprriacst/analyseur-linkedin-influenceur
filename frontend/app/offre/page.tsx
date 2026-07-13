"use client";

/**
 * Page d'abonnement (/offre) — un seul écran, format « closing call ».
 *
 * Gauche : la promesse. Droite : création de compte + départ immédiat vers le
 * paiement Stripe. Pas de scroll, pas de blabla : le prospect est en appel, on
 * lui montre l'offre et on le fait signer.
 *
 * ⚠️ Le paiement passe OBLIGATOIREMENT par un compte : les crédits sont attribués
 * par le webhook Stripe, qui doit savoir à quel compte rattacher la facture. Un
 * lien de paiement brut = un client qui paie sans jamais recevoir ses crédits.
 * D'où le formulaire intégré : compte créé → redirection Stripe dans la foulée.
 */

import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, Lock } from "lucide-react";
import { supabase, authHeaders } from "../lib/supabase";

const DIRECT_API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "https://analyseur-linkedin-influenceur-api-eu.onrender.com";

// Même clé que dans Home : si la confirmation d'e-mail est activée, l'intention
// survit et Home reprend le paiement à la première connexion.
const SUBSCRIBE_INTENT_KEY = "cibl_subscribe_intent";

const PROMISES: string[] = [
  "L'analyse chiffrée de ce qui marche vraiment chez tes concurrents LinkedIn",
  "Des posts générés dans ta voix, à partir de ce qui performe sur ton marché",
  "Une idée de post chaque matin, publication et programmation incluses",
  "Les prospects qui commentent les posts de tes concurrents, contactés depuis l'app",
];

export default function OffrePage() {
  const [price, setPrice] = useState("49 €");
  const [credits, setCredits] = useState(1000);
  const [mode, setMode] = useState<"signup" | "signin">("signup");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(false);

  // Prix lu depuis Stripe (source de vérité) — repli sur 49 € si injoignable.
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${DIRECT_API_URL}/billing/plan`);
        if (!res.ok) return;
        const plan = (await res.json())?.plan;
        if (!plan) return;
        if (typeof plan.credits === "number") setCredits(plan.credits);
        if (typeof plan.amount === "number") {
          setPrice(new Intl.NumberFormat("fr-FR", {
            style: "currency",
            currency: (plan.currency || "eur").toUpperCase(),
            maximumFractionDigits: plan.amount % 1 === 0 ? 0 : 2,
          }).format(plan.amount));
        }
      } catch { /* repli silencieux */ }
    })();
  }, []);

  /** Compte prêt (session active) → session Checkout → redirection Stripe. */
  async function goCheckout() {
    const res = await fetch(`${DIRECT_API_URL}/me/billing/checkout`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(await authHeaders()) },
      body: JSON.stringify({
        success_url: `${window.location.origin}/?billing=success`,
        cancel_url: `${window.location.origin}/offre`,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Paiement indisponible — réessaie dans un instant.");
    window.location.href = data.url;
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setInfo("");
    setLoading(true);
    try {
      if (mode === "signin") {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
        await goCheckout();
        return; // redirection en cours — on garde le spinner
      }
      const { data, error } = await supabase.auth.signUp({
        email,
        password,
        options: { data: { onboarding_pending: true } },
      });
      if (error) throw error;
      if (data.session) {
        await goCheckout();
        return;
      }
      // Confirmation d'e-mail activée : pas de session tout de suite. On mémorise
      // l'intention — Home enchaînera sur le paiement à la première connexion.
      try { localStorage.setItem(SUBSCRIBE_INTENT_KEY, String(Date.now())); } catch { /* ignore */ }
      setInfo("Compte créé ! Confirme ton e-mail : à ta première connexion, tu seras redirigé vers le paiement.");
      setMode("signin");
      setLoading(false);
    } catch (err: any) {
      setError(err.message || "Une erreur est survenue.");
      setLoading(false);
    }
  }

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "grid",
        gridTemplateColumns: "minmax(0, 1.1fr) minmax(0, 1fr)",
      }}
      className="offre-split"
    >
      {/* ── Gauche : la promesse ── */}
      <section
        style={{
          background: "linear-gradient(160deg, #34368f 0%, #4648d4 55%, #6063ee 100%)",
          color: "#fff",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "56px clamp(28px, 6vw, 80px)",
        }}
      >
        <p style={{ margin: 0, fontSize: 14, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", opacity: 0.85 }}>
          Cibl
        </p>
        <h1 style={{ margin: "18px 0 0", fontSize: "clamp(28px, 3.2vw, 40px)", lineHeight: 1.15, letterSpacing: "-0.02em" }}>
          Arrête de deviner ce qui marche sur LinkedIn.
        </h1>
        <ul style={{ listStyle: "none", padding: 0, margin: "32px 0 0", display: "grid", gap: 16 }}>
          {PROMISES.map((promise) => (
            <li key={promise} style={{ display: "flex", gap: 12, alignItems: "flex-start", fontSize: 15, lineHeight: 1.55 }}>
              <CheckCircle2 size={18} style={{ flexShrink: 0, marginTop: 3, opacity: 0.9 }} />
              <span style={{ opacity: 0.95 }}>{promise}</span>
            </li>
          ))}
        </ul>
        <div
          style={{
            marginTop: 40,
            display: "inline-flex",
            alignItems: "baseline",
            gap: 10,
            flexWrap: "wrap",
          }}
        >
          <span style={{ fontSize: 38, fontWeight: 700, letterSpacing: "-0.02em" }}>{price}</span>
          <span style={{ fontSize: 15, opacity: 0.85 }}>/ mois</span>
        </div>
        <p style={{ margin: "6px 0 0", fontSize: 14, opacity: 0.85 }}>
          {credits.toLocaleString("fr-FR")} crédits rechargés chaque mois · sans engagement · résiliable en un clic
        </p>
      </section>

      {/* ── Droite : compte + paiement ── */}
      <section
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "48px clamp(20px, 5vw, 64px)",
          background: "var(--surface-low)",
        }}
      >
        <form onSubmit={submit} style={{ width: "100%", maxWidth: 380 }}>
          <h2 style={{ margin: 0, fontSize: 22, letterSpacing: "-0.02em" }}>
            {mode === "signup" ? "Crée ton compte et abonne-toi" : "Connecte-toi pour t'abonner"}
          </h2>
          <p style={{ margin: "8px 0 20px", fontSize: 14, color: "var(--muted)", lineHeight: 1.5 }}>
            {mode === "signup"
              ? "30 secondes : ton compte, puis le paiement sécurisé Stripe."
              : "Tu seras redirigé vers le paiement sécurisé Stripe."}
          </p>

          <label className="auth-label">Email</label>
          <input
            className="auth-input"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="toi@exemple.com"
            autoComplete="email"
          />

          <label className="auth-label">Mot de passe</label>
          <input
            className="auth-input"
            type="password"
            required
            minLength={6}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            autoComplete={mode === "signup" ? "new-password" : "current-password"}
          />

          {error && <div className="error" style={{ marginTop: 12 }}>{error}</div>}
          {info && <div className="auth-info" style={{ marginTop: 12 }}>{info}</div>}

          <button className="auth-submit" type="submit" disabled={loading} style={{ marginTop: 16 }}>
            {loading ? <Loader2 className="spin" size={16} /> : mode === "signup" ? "Créer mon compte et payer" : "Se connecter et payer"}
          </button>

          <button
            type="button"
            className="auth-switch"
            onClick={() => { setMode(mode === "signup" ? "signin" : "signup"); setError(""); setInfo(""); }}
          >
            {mode === "signup" ? "Déjà un compte ? Se connecter" : "Pas de compte ? En créer un"}
          </button>

          <p style={{ margin: "20px 0 0", fontSize: 12.5, color: "var(--muted)", display: "flex", alignItems: "center", gap: 6, justifyContent: "center" }}>
            <Lock size={13} /> Paiement sécurisé par Stripe — carte gérée par Stripe, jamais par nous.
          </p>
        </form>
      </section>

      {/* Mobile : les deux colonnes s'empilent */}
      <style>{`
        @media (max-width: 820px) {
          .offre-split { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </main>
  );
}

"use client";

/**
 * Démarrage de l'essai gratuit (/essai) — repli du tunnel fondateurs.
 *
 *   /onboarding → compte créé → essai direct (sans carte) → app
 *   ou ici si l'état de facturation était illisible au moment du compte.
 *
 * ⚠️ Le droit à l'essai est décidé **côté serveur** (`trial_eligible` de
 * `/me/billing`) : un compte qui a déjà eu un abonnement repart sur un paiement
 * immédiat (carte requise via Checkout).
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, CreditCard, Loader2, Rocket } from "lucide-react";
import { supabase, authHeaders } from "../lib/supabase";
import { FOUNDERS_MONTHLY_SEATS, FOUNDERS_GUARANTEE_DAYS } from "../lib/founders";

const DIRECT_API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "https://analyseur-linkedin-influenceur-api-eu.onrender.com";

const PROMISES: string[] = [
  "L'analyse chiffrée de ce qui marche vraiment chez les fondateurs de ta catégorie",
  "Des posts écrits dans ta voix, à partir de ce qui performe sur ton marché",
  "Une idée de post chaque matin, publication et programmation incluses",
  "Ton audience repérée dans les commentaires de tes concurrents, contacté depuis l'app",
];

/** Jalons de l'essai sans carte — ce qui se passe et quand. */
function timeline(days: number, price: string): { day: string; text: string }[] {
  return [
    { day: "Aujourd'hui", text: "Ton accès complet s'ouvre. Aucun prélèvement, aucune carte." },
    {
      day: `Jours 1 à ${days}`,
      text: "Tu testes Cibl librement. Rien ne part sans que tu ajoutes un moyen de paiement.",
    },
    {
      day: `Jour ${days}`,
      text: `L'essai se termine. Pour continuer : ${price}/mois depuis ton espace (carte à ce moment-là).`,
    },
    {
      day: "Après l'essai",
      text: `Satisfait ou remboursé pendant ${FOUNDERS_GUARANTEE_DAYS} jours — le premier mois remboursé sur simple demande.`,
    },
  ];
}

export default function EssaiPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [price, setPrice] = useState("49 €");
  const [credits, setCredits] = useState(1000);
  const [trialDays, setTrialDays] = useState(7);
  const [trialEligible, setTrialEligible] = useState(false);
  const [alreadySubscribed, setAlreadySubscribed] = useState(false);

  useEffect(() => {
    (async () => {
      const { data } = await supabase.auth.getSession();
      if (!data.session) {
        router.replace("/onboarding");
        return;
      }
      try {
        const res = await fetch(`${DIRECT_API_URL}/me/billing`, { headers: await authHeaders() });
        if (res.ok) {
          const state = await res.json();
          if (state?.subscribed) {
            setAlreadySubscribed(true);
          }
          setTrialEligible(!!state?.trial_eligible);
          if (typeof state?.trial_days === "number" && state.trial_days > 0) setTrialDays(state.trial_days);
          const plan = state?.plan;
          if (plan) {
            if (typeof plan.credits === "number") setCredits(plan.credits);
            if (typeof plan.amount === "number") {
              setPrice(
                new Intl.NumberFormat("fr-FR", {
                  style: "currency",
                  currency: (plan.currency || "eur").toUpperCase(),
                  maximumFractionDigits: plan.amount % 1 === 0 ? 0 : 2,
                }).format(plan.amount)
              );
            }
          }
        }
      } catch { /* repli sur les valeurs par défaut */ }
      setReady(true);
    })();
  }, [router]);

  async function startTrial() {
    setError("");
    setLoading(true);
    try {
      if (trialEligible) {
        const res = await fetch(`${DIRECT_API_URL}/me/billing/start-trial`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || "Essai indisponible — réessaie dans un instant.");
        router.push("/?billing=trial_started");
        return;
      }

      const res = await fetch(`${DIRECT_API_URL}/me/billing/checkout`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({
          trial: false,
          success_url: `${window.location.origin}/?billing=success`,
          cancel_url: `${window.location.origin}/?billing=cancelled`,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Paiement indisponible — réessaie dans un instant.");
      window.location.href = data.url;
    } catch (err: any) {
      setError(err.message || "Une erreur est survenue.");
      setLoading(false);
    }
  }

  if (!ready) {
    return (
      <main style={{ minHeight: "100vh", display: "grid", placeItems: "center", background: "var(--surface-low)" }}>
        <Loader2 className="spin" size={28} style={{ color: "var(--primary)" }} />
      </main>
    );
  }

  return (
    <main className="offre-split" style={{ minHeight: "100vh", display: "grid", gridTemplateColumns: "minmax(0, 1.1fr) minmax(0, 1fr)" }}>
      <section
        style={{
          position: "relative",
          overflow: "hidden",
          background: "linear-gradient(158deg, #2b2d7e 0%, #4648d4 58%, #5d60ea 100%)",
          color: "#fff",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "64px clamp(28px, 6vw, 84px)",
        }}
      >
        <div aria-hidden style={{ position: "absolute", top: -140, right: -120, width: 420, height: 420, borderRadius: "50%", background: "radial-gradient(circle, rgba(255,255,255,0.14) 0%, rgba(255,255,255,0) 65%)" }} />
        <div aria-hidden style={{ position: "absolute", bottom: -180, left: -140, width: 480, height: 480, borderRadius: "50%", background: "radial-gradient(circle, rgba(0,0,0,0.22) 0%, rgba(0,0,0,0) 65%)" }} />

        <div style={{ position: "relative" }}>
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 7,
              padding: "6px 14px",
              borderRadius: 20,
              fontSize: 13,
              fontWeight: 700,
              background: "rgba(255,255,255,0.14)",
              border: "1px solid rgba(255,255,255,0.28)",
            }}
          >
            <Rocket size={14} /> {trialDays} jours d&apos;accès complet
          </span>
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 7,
              marginLeft: 10,
              padding: "6px 14px",
              borderRadius: 20,
              fontSize: 13,
              fontWeight: 700,
              background: "rgba(255,255,255,0.10)",
              border: "1px solid rgba(255,255,255,0.22)",
            }}
          >
            {FOUNDERS_MONTHLY_SEATS} comptes fondateurs / mois
          </span>

          <h1 style={{ margin: "22px 0 0", fontSize: "clamp(28px, 3.2vw, 40px)", lineHeight: 1.14, letterSpacing: "-0.025em", maxWidth: 560 }}>
            Teste Cibl sur ton vrai marché,<br />
            <span style={{ background: "linear-gradient(transparent 68%, rgba(255,255,255,0.32) 68%)" }}>
              pendant {trialDays} jours.
            </span>
          </h1>

          <ul style={{ listStyle: "none", padding: 0, margin: "30px 0 0", display: "grid", gap: 14, maxWidth: 580 }}>
            {PROMISES.map((promise) => (
              <li key={promise} style={{ display: "flex", gap: 12, alignItems: "flex-start", fontSize: 15, lineHeight: 1.55 }}>
                <span style={{ display: "grid", placeItems: "center", width: 24, height: 24, borderRadius: "50%", background: "rgba(255,255,255,0.14)", flexShrink: 0, marginTop: 1 }}>
                  <CheckCircle2 size={14} />
                </span>
                <span style={{ opacity: 0.96 }}>{promise}</span>
              </li>
            ))}
          </ul>

          <div
            style={{
              margin: "30px 0 0",
              maxWidth: 460,
              padding: "18px 20px",
              borderRadius: 14,
              background: "rgba(255,255,255,0.09)",
              border: "1px solid rgba(255,255,255,0.18)",
              display: "grid",
              gap: 12,
            }}
          >
            {timeline(trialDays, price).map((item) => (
              <div key={item.day} style={{ display: "flex", gap: 12, alignItems: "flex-start", fontSize: 13.5, lineHeight: 1.5 }}>
                <strong style={{ minWidth: 92, opacity: 0.95 }}>{item.day}</strong>
                <span style={{ opacity: 0.85 }}>{item.text}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 18,
          padding: "48px clamp(20px, 5vw, 64px)",
          background:
            "radial-gradient(circle at 85% 12%, rgba(70,72,212,0.06) 0%, rgba(70,72,212,0) 42%), var(--surface-low)",
        }}
      >
        <div className="auth-card" style={{ maxWidth: 420, padding: 32, gap: 0, textAlign: "center" }}>
          {alreadySubscribed ? (
            <>
              <h2 className="auth-title" style={{ fontSize: 22 }}>Ton accès est déjà ouvert</h2>
              <p className="auth-sub">Rien à faire ici — ton espace t&apos;attend.</p>
              <button
                className="auth-submit"
                type="button"
                onClick={() => router.push("/")}
                style={{ marginTop: 18, height: 48, fontSize: 15 }}
              >
                Aller dans l&apos;app
              </button>
            </>
          ) : (
            <>
              <div style={{ display: "flex", alignItems: "baseline", justifyContent: "center", gap: 10 }}>
                <span style={{ fontSize: 46, fontWeight: 800, letterSpacing: "-0.025em" }}>
                  {trialEligible ? "0 €" : price}
                </span>
                <span style={{ fontSize: 16, color: "var(--muted)" }}>
                  {trialEligible ? `pendant ${trialDays} jours` : "/ mois"}
                </span>
              </div>

              <p style={{ margin: "8px 0 0", fontSize: 14.5, color: "var(--muted)" }}>
                {trialEligible ? (
                  <>
                    Puis {price}/mois si tu continues · {credits.toLocaleString("fr-FR")} crédits par mois ·
                    sans engagement
                  </>
                ) : (
                  <>
                    {credits.toLocaleString("fr-FR")} crédits rechargés chaque mois · sans engagement ·
                    résiliable en un clic
                  </>
                )}
              </p>

              <p
                style={{
                  margin: "16px 0 0",
                  padding: "11px 14px",
                  borderRadius: 12,
                  fontSize: 13.5,
                  lineHeight: 1.55,
                  color: "var(--ink)",
                  background: "rgba(70,72,212,0.06)",
                  border: "1px solid rgba(70,72,212,0.16)",
                }}
              >
                {trialEligible ? (
                  <>
                    <strong>Aucune carte demandée pour démarrer.</strong> Tu pourras t&apos;abonner
                    depuis ton espace avant la fin des {trialDays} jours si tu veux continuer.
                  </>
                ) : (
                  <>
                    Ce compte a déjà eu un abonnement : l&apos;essai gratuit ne s&apos;applique
                    qu&apos;à un premier abonnement. Tu repars donc sur{" "}
                    <strong>{price}/mois</strong>, résiliable à tout moment.
                  </>
                )}
              </p>

              {error && <div className="error" style={{ marginTop: 14 }}>{error}</div>}

              <button
                className="auth-submit"
                type="button"
                onClick={startTrial}
                disabled={loading}
                style={{ marginTop: 18, height: 48, fontSize: 15, display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}
              >
                {loading ? (
                  <Loader2 className="spin" size={16} />
                ) : trialEligible ? (
                  <><Rocket size={16} /> Démarrer mes {trialDays} jours gratuits</>
                ) : (
                  <><CreditCard size={16} /> S&apos;abonner — {price}/mois</>
                )}
              </button>

              {!trialEligible && (
                <p style={{ margin: "14px 0 0", fontSize: 12, color: "var(--muted)" }}>
                  Paiement sécurisé par Stripe
                </p>
              )}

              <button
                type="button"
                className="auth-switch"
                onClick={() => router.push("/")}
                style={{ marginTop: 10 }}
              >
                Plus tard — entrer dans l&apos;app
              </button>
            </>
          )}
        </div>
      </section>
    </main>
  );
}

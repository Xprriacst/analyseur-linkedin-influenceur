"use client";

/**
 * Page de paiement (/paiement) — dernière étape du parcours d'acquisition.
 *
 *   landing → onboarding → compte créé → **ici** → Stripe → app
 *
 * Le compte existe déjà (créé sur /start) : cette page ne fait donc PAS d'inscription.
 * Elle révèle l'offre de lancement et lance le paiement Stripe pour la session en cours.
 *
 * ⚠️ « Tu gardes 49 € » est une promesse qui se tient DANS STRIPE, pas ici : un
 * abonnement reste attaché au tarif sur lequel il a été souscrit. Le jour du passage
 * à 150 €, il faut créer un NOUVEAU tarif — les abonnés à 49 € y restent seuls.
 * Modifier le tarif existant les ferait TOUS basculer et trahirait cette page.
 *
 * Accès direct sans session (lien partagé, retour arrière) → on renvoie sur /start :
 * sans compte, il n'y a personne à qui rattacher la facture Stripe.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, Flame, Loader2, Lock, TrendingDown, TrendingUp } from "lucide-react";
import { supabase, authHeaders } from "../lib/supabase";

const DIRECT_API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "https://analyseur-linkedin-influenceur-api-eu.onrender.com";

const LAUNCH_SEATS = 150;
const FUTURE_PRICE = "150 €";

const PROMISES: string[] = [
  "L'analyse chiffrée de ce qui marche vraiment chez tes concurrents LinkedIn",
  "Des posts générés dans ta voix, à partir de ce qui performe sur ton marché",
  "Une idée de post chaque matin, publication et programmation incluses",
  "Les prospects qui commentent les posts de tes concurrents, contactés depuis l'app",
];

/** Tendances réellement mesurées par l'outil — pas des chiffres marketing inventés. */
const PROOF_STATS: { up: boolean; text: string }[] = [
  { up: true, text: "Appels à commenter : engagement ×2,5" },
  { up: true, text: "Posts texte : +22 % — reposts : −84 %" },
  { up: false, text: "Publier tous les jours : taux divisé par 4" },
];

export default function PaiementPage() {
  const router = useRouter();
  const [price, setPrice] = useState("49 €");
  const [credits, setCredits] = useState(1000);
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Sans session → personne à facturer. Retour au parcours.
  useEffect(() => {
    (async () => {
      const { data } = await supabase.auth.getSession();
      if (!data.session) {
        router.replace("/start");
        return;
      }
      setReady(true);
    })();
  }, [router]);

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
          setPrice(
            new Intl.NumberFormat("fr-FR", {
              style: "currency",
              currency: (plan.currency || "eur").toUpperCase(),
              maximumFractionDigits: plan.amount % 1 === 0 ? 0 : 2,
            }).format(plan.amount)
          );
        }
      } catch { /* repli silencieux */ }
    })();
  }, []);

  async function subscribe() {
    setError("");
    setLoading(true);
    try {
      const res = await fetch(`${DIRECT_API_URL}/me/billing/checkout`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({
          success_url: `${window.location.origin}/?billing=success`,
          // Paiement abandonné → il entre quand même dans l'app avec ses crédits
          // offerts, profil déjà enregistré. Rien de ce qu'il a fait n'est perdu.
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
      {/* ── Gauche : la promesse + l'offre de lancement ── */}
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
            <Flame size={14} /> Offre de lancement — {LAUNCH_SEATS} premiers clients
          </span>

          <h1 style={{ margin: "22px 0 0", fontSize: "clamp(28px, 3.2vw, 40px)", lineHeight: 1.14, letterSpacing: "-0.025em", maxWidth: 560 }}>
            Dernière étape :<br />
            <span style={{ background: "linear-gradient(transparent 68%, rgba(255,255,255,0.32) 68%)" }}>lance ton abonnement.</span>
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

          {/* Preuve : tendances réellement mesurées par l'outil */}
          <div
            style={{
              margin: "30px 0 0",
              maxWidth: 460,
              padding: "16px 18px",
              borderRadius: 14,
              background: "rgba(255,255,255,0.09)",
              border: "1px solid rgba(255,255,255,0.18)",
              backdropFilter: "blur(4px)",
            }}
          >
            <p style={{ margin: "0 0 10px", fontSize: 11.5, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", opacity: 0.75 }}>
              Mesuré sur de vraies analyses — pas du feeling
            </p>
            <div style={{ display: "grid", gap: 8 }}>
              {PROOF_STATS.map((stat) => (
                <div key={stat.text} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13.5 }}>
                  {stat.up
                    ? <TrendingUp size={15} style={{ color: "#7ef0c0", flexShrink: 0 }} />
                    : <TrendingDown size={15} style={{ color: "#ffb4a8", flexShrink: 0 }} />}
                  <span style={{ opacity: 0.95 }}>{stat.text}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── Droite : l'offre chiffrée + le paiement ── */}
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
          <span
            style={{
              alignSelf: "center",
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "4px 10px",
              borderRadius: 20,
              fontSize: 12,
              fontWeight: 600,
              color: "var(--primary)",
              background: "rgba(70,72,212,0.08)",
              border: "1px solid rgba(70,72,212,0.18)",
            }}
          >
            <Flame size={12} /> Prix de lancement
          </span>

          <div style={{ marginTop: 16, display: "flex", alignItems: "baseline", justifyContent: "center", gap: 10 }}>
            <span style={{ fontSize: 46, fontWeight: 800, letterSpacing: "-0.025em" }}>{price}</span>
            <span style={{ fontSize: 22, fontWeight: 600, color: "var(--muted)", textDecoration: "line-through" }}>{FUTURE_PRICE}</span>
            <span style={{ fontSize: 16, color: "var(--muted)" }}>/ mois</span>
          </div>
          <p style={{ margin: "8px 0 0", fontSize: 14.5, color: "var(--muted)" }}>
            {credits.toLocaleString("fr-FR")} crédits rechargés chaque mois · sans engagement · résiliable en un clic
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
            Passé les {LAUNCH_SEATS} premiers clients, l'abonnement passera à{" "}
            <strong>{FUTURE_PRICE}/mois</strong>. En t'abonnant maintenant, tu gardes{" "}
            <strong>{price}/mois</strong> tant que ton abonnement reste actif.
          </p>

          {error && <div className="error" style={{ marginTop: 14 }}>{error}</div>}

          <button
            className="auth-submit"
            type="button"
            onClick={subscribe}
            disabled={loading}
            style={{ marginTop: 18, height: 48, fontSize: 15, display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}
          >
            {loading ? <Loader2 className="spin" size={16} /> : <>S'abonner — {price}/mois</>}
          </button>
        </div>

        <p style={{ margin: 0, fontSize: 12.5, color: "var(--muted)", display: "flex", alignItems: "center", gap: 6 }}>
          <Lock size={13} /> Paiement sécurisé par Stripe — ta carte est gérée par Stripe, jamais par nous.
        </p>
      </section>

      {/* Mobile : les deux colonnes s'empilent */}
      <style>{`
        @media (max-width: 860px) {
          .offre-split { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </main>
  );
}

"use client";

/**
 * Page de vente publique (/offre) — à montrer en appel de closing.
 *
 * Le bouton renvoie vers `/?subscribe=1`, PAS vers un lien de paiement Stripe brut :
 * les crédits sont attribués par le webhook, qui a besoin de savoir à quel compte
 * rattacher le paiement. Un paiement fait hors compte n'est rattachable à personne
 * → le client paierait sans jamais recevoir ses crédits.
 */

import { useEffect, useState } from "react";
import { ArrowRight, CheckCircle2 } from "lucide-react";

const DIRECT_API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "https://analyseur-linkedin-influenceur-api-eu.onrender.com";

const FALLBACK_PRICE = "49 € par mois";
const FALLBACK_CREDITS = 1000;

/** Ce que couvre l'abonnement, dans l'ordre de la valeur perçue. */
const FEATURES: { title: string; detail: string }[] = [
  {
    title: "Décrypte la stratégie de tes concurrents",
    detail:
      "Analyse leurs posts LinkedIn : ce qui marche vraiment chez eux — formats, accroches, appels à l'action, rythme de publication — chiffres à l'appui, pas au feeling.",
  },
  {
    title: "Des posts écrits dans ta voix",
    detail:
      "La génération s'appuie sur ton contexte éditorial et sur ce que l'analyse a repéré comme performant dans ton marché. Tu gardes la main : tout est relisable et modifiable.",
  },
  {
    title: "Une idée de post chaque matin",
    detail:
      "Livrée automatiquement, piochée en priorité dans ton réservoir d'idées. Plus de page blanche le lundi.",
  },
  {
    title: "Publication et programmation LinkedIn",
    detail:
      "Publie ou programme depuis l'app, avec validation par Slack si tu veux relire avant. Images IA incluses pour illustrer tes posts.",
  },
  {
    title: "Prospection : des leads qui se sont déjà manifestés",
    detail:
      "Récupère les gens qui commentent les posts de tes concurrents, filtre-les sur ton client idéal, et envoie invitation puis premier message directement depuis l'app.",
  },
  {
    title: "Une seule boîte de réception",
    detail: "Tes conversations LinkedIn et Instagram au même endroit, avec des réponses suggérées par l'IA.",
  },
];

/** Rendre 1000 crédits concrets : ce qu'on peut en faire en un mois. */
const CREDIT_EXAMPLES: { label: string; cost: string }[] = [
  { label: "10 analyses de concurrents", cost: "200 crédits" },
  { label: "60 posts générés", cost: "300 crédits" },
  { label: "30 images IA", cost: "150 crédits" },
  { label: "100 échanges avec l'agent IA", cost: "200 crédits" },
  { label: "300 leads collectés", cost: "100 crédits" },
];

export default function OffrePage() {
  const [price, setPrice] = useState(FALLBACK_PRICE);
  const [credits, setCredits] = useState(FALLBACK_CREDITS);

  // Le prix vient de Stripe (source de vérité) — la page ne peut pas mentir si le
  // tarif change. En cas d'API injoignable, on garde l'affichage par défaut.
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${DIRECT_API_URL}/billing/plan`);
        if (!res.ok) return;
        const data = await res.json();
        const plan = data?.plan;
        if (!plan) return;
        if (typeof plan.credits === "number") setCredits(plan.credits);
        if (typeof plan.amount === "number") {
          const amount = new Intl.NumberFormat("fr-FR", {
            style: "currency",
            currency: (plan.currency || "eur").toUpperCase(),
            maximumFractionDigits: plan.amount % 1 === 0 ? 0 : 2,
          }).format(plan.amount);
          setPrice(plan.interval === "year" ? `${amount} par an` : `${amount} par mois`);
        }
      } catch {
        /* on garde l'affichage par défaut */
      }
    })();
  }, []);

  return (
    <main style={{ maxWidth: 880, margin: "0 auto", padding: "56px 24px 80px" }}>
      <header style={{ textAlign: "center", marginBottom: 40 }}>
        <p style={{ margin: 0, fontSize: 13, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--muted)" }}>
          Cibl
        </p>
        <h1 style={{ margin: "12px 0 0", fontSize: 40, lineHeight: 1.15, letterSpacing: "-0.03em" }}>
          Arrête de deviner ce qui marche sur LinkedIn.
        </h1>
        <p style={{ margin: "16px auto 0", maxWidth: 620, fontSize: 17, lineHeight: 1.6, color: "var(--muted)" }}>
          Cibl analyse ce qui fonctionne réellement chez tes concurrents, écrit tes posts à partir de ça,
          et te ramène les prospects qui commentent les leurs.
        </p>
      </header>

      <section
        className="card"
        style={{ textAlign: "center", padding: "32px 24px", marginBottom: 40 }}
      >
        <div style={{ fontSize: 34, fontWeight: 700, letterSpacing: "-0.02em" }}>{price}</div>
        <p style={{ margin: "8px 0 0", color: "var(--muted)" }}>
          {credits.toLocaleString("fr-FR")} crédits rechargés chaque mois. Sans engagement, résiliable en un clic.
        </p>
        <a
          href="/?subscribe=1"
          className="primary-button"
          style={{ display: "inline-flex", marginTop: 24, textDecoration: "none", padding: "12px 22px", fontSize: 15 }}
        >
          S'abonner <ArrowRight size={16} />
        </a>
        <p style={{ margin: "14px 0 0", fontSize: 13, color: "var(--muted)" }}>
          Paiement sécurisé par Stripe. Tu crées ton compte, puis tu es redirigé vers le paiement.
        </p>
      </section>

      <section style={{ marginBottom: 40 }}>
        <h2 style={{ fontSize: 22, letterSpacing: "-0.02em", marginBottom: 20 }}>Ce que tu obtiens</h2>
        <div style={{ display: "grid", gap: 14 }}>
          {FEATURES.map((feature) => (
            <div key={feature.title} className="card" style={{ display: "flex", gap: 12, padding: 18 }}>
              <CheckCircle2 size={18} color="#047857" style={{ flexShrink: 0, marginTop: 2 }} />
              <div>
                <strong style={{ display: "block", marginBottom: 4 }}>{feature.title}</strong>
                <span style={{ color: "var(--muted)", fontSize: 14, lineHeight: 1.6 }}>{feature.detail}</span>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section style={{ marginBottom: 40 }}>
        <h2 style={{ fontSize: 22, letterSpacing: "-0.02em", marginBottom: 8 }}>
          {credits.toLocaleString("fr-FR")} crédits, concrètement
        </h2>
        <p style={{ margin: "0 0 20px", color: "var(--muted)", fontSize: 14 }}>
          Chaque action consomme des crédits. Voilà à quoi ressemble un mois type — le tout tient largement
          dans l'abonnement.
        </p>
        <div className="card" style={{ padding: 4 }}>
          {CREDIT_EXAMPLES.map((example, index) => (
            <div
              key={example.label}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: 12,
                padding: "13px 16px",
                borderTop: index === 0 ? "none" : "1px solid var(--border)",
              }}
            >
              <span style={{ fontSize: 14 }}>{example.label}</span>
              <span style={{ fontSize: 13, color: "var(--muted)", whiteSpace: "nowrap" }}>{example.cost}</span>
            </div>
          ))}
        </div>
      </section>

      <section style={{ textAlign: "center" }}>
        <a
          href="/?subscribe=1"
          className="primary-button"
          style={{ display: "inline-flex", textDecoration: "none", padding: "12px 22px", fontSize: 15 }}
        >
          Démarrer maintenant <ArrowRight size={16} />
        </a>
        <p style={{ margin: "14px 0 0", fontSize: 13, color: "var(--muted)" }}>
          Tu veux d'abord essayer ? <a href="/">Crée un compte gratuit</a> — 60 crédits offerts, sans carte bancaire.
        </p>
      </section>
    </main>
  );
}

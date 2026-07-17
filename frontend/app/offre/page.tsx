"use client";

/**
 * Landing publique (/offre) — la page de vente.
 *
 * Elle ne fait qu'UNE chose : amener sur /start (le parcours guidé qui analyse,
 * questionne, crée le compte puis encaisse). Aucun formulaire ici : on ne demande
 * ni e-mail ni carte avant d'avoir montré le travail fait.
 *
 * ⚠️ Les chiffres de PROOF_STATS sont des tendances RÉELLEMENT mesurées par l'outil
 * (corpus ~400 posts, 17 rapports) — pas des chiffres marketing inventés. Ne pas en
 * ajouter sans la mesure derrière. Idem pour les témoignages : la section n'existe
 * pas tant qu'il n'y a pas de vraies citations de vrais clients.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  BarChart3,
  CheckCircle2,
  Inbox,
  Lightbulb,
  Lock,
  PenLine,
  Radar,
  Target,
  TrendingDown,
  TrendingUp,
  Users,
} from "lucide-react";

const DIRECT_API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "https://analyseur-linkedin-influenceur-api-eu.onrender.com";

/** Tendances réellement mesurées par l'outil sur le corpus analysé. */
const PROOF_STATS: { up: boolean; text: string }[] = [
  { up: true, text: "Appels à commenter : engagement ×2,5" },
  { up: true, text: "Posts texte : +22 % — reposts : −84 %" },
  { up: false, text: "Publier tous les jours : taux divisé par 4" },
];

const STEPS: { n: string; title: string; body: string }[] = [
  {
    n: "01",
    title: "Tu colles ton profil LinkedIn",
    body: "On le lit, on comprend ton métier, ta cible et ce que tu vends. Quelques questions pour affiner, et c'est plié.",
  },
  {
    n: "02",
    title: "On décrypte ton marché",
    body: "Les comptes qui performent dans ton secteur, passés au crible : formats, accroches, rythme, appels à l'action. Chiffré, pas au feeling.",
  },
  {
    n: "03",
    title: "L'app écrit tes posts",
    body: "Dans ta voix, sur les structures qui marchent vraiment chez toi. Une idée chaque matin si tu veux, sinon à la demande.",
  },
  {
    n: "04",
    title: "Tu publies et tu contactes",
    body: "Publication et programmation depuis l'app. Et les gens qui commentent les posts de tes concurrents deviennent tes prospects.",
  },
];

const FEATURES: { icon: React.ReactNode; title: string; body: string }[] = [
  {
    icon: <BarChart3 size={18} />,
    title: "Analyse d'influenceurs",
    body: "N'importe quel compte de ton marché décortiqué : ce qui marche, ce qui ne marche pas, et pourquoi.",
  },
  {
    icon: <PenLine size={18} />,
    title: "Générateur de posts",
    body: "Un parcours guidé : ton idée, ton angle, la structure la mieux adaptée. Le post sort écrit dans ta voix.",
  },
  {
    icon: <Lightbulb size={18} />,
    title: "Idée du jour",
    body: "Une idée de post chaque matin, piochée dans ton réservoir et calée sur ce qui performe.",
  },
  {
    icon: <Radar size={18} />,
    title: "Veille",
    body: "Les nouveaux posts des comptes que tu suis, dès qu'ils sortent. De quoi t'en inspirer avant tout le monde.",
  },
  {
    icon: <Users size={18} />,
    title: "Prospection LinkedIn",
    body: "Les prospects qui commentent les posts de tes concurrents, contactés depuis l'app — à un rythme qui protège ton compte.",
  },
  {
    icon: <Inbox size={18} />,
    title: "Inbox",
    body: "Tes conversations LinkedIn et Instagram au même endroit, avec des réponses proposées par l'IA.",
  },
];

/** Bouton principal — même destination partout : le parcours guidé. */
function StartButton({ label = "Commencer", light = false }: { label?: string; light?: boolean }) {
  return (
    <Link
      href="/start"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        height: 48,
        padding: "0 24px",
        borderRadius: 12,
        fontSize: 15,
        fontWeight: 700,
        textDecoration: "none",
        background: light ? "#fff" : "var(--primary)",
        color: light ? "#2b2d7e" : "#fff",
        boxShadow: light ? "0 8px 24px rgba(0,0,0,0.18)" : "0 8px 24px rgba(70,72,212,0.28)",
      }}
    >
      {label} <ArrowRight size={16} />
    </Link>
  );
}

export default function OffrePage() {
  const [price, setPrice] = useState("49 €");
  const [credits, setCredits] = useState(1000);

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
      } catch {
        /* repli silencieux */
      }
    })();
  }, []);

  return (
    <main style={{ background: "var(--surface-low)" }}>
      {/* ── Barre de navigation ── */}
      <nav
        style={{
          position: "sticky",
          top: 0,
          zIndex: 10,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
          padding: "14px clamp(20px, 5vw, 56px)",
          background: "rgba(43,45,126,0.92)",
          backdropFilter: "blur(8px)",
          color: "#fff",
        }}
      >
        <Link href="/offre" style={{ display: "flex", alignItems: "center", gap: 10, color: "#fff", textDecoration: "none" }}>
          <span
            style={{
              display: "grid",
              placeItems: "center",
              width: 32,
              height: 32,
              borderRadius: 10,
              background: "rgba(255,255,255,0.16)",
              border: "1px solid rgba(255,255,255,0.25)",
            }}
          >
            <Target size={17} />
          </span>
          <span style={{ fontSize: 16, fontWeight: 800, letterSpacing: "0.06em" }}>Cibl</span>
        </Link>

        <div style={{ display: "flex", alignItems: "center", gap: 22 }}>
          <a href="#comment" className="lp-navlink">Comment ça marche</a>
          <a href="#fonctionnalites" className="lp-navlink">Fonctionnalités</a>
          <a href="#tarif" className="lp-navlink">Tarif</a>
          <Link href="/" className="lp-navlink">Se connecter</Link>
          <Link
            href="/start"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              height: 38,
              padding: "0 16px",
              borderRadius: 10,
              fontSize: 14,
              fontWeight: 700,
              textDecoration: "none",
              background: "#fff",
              color: "#2b2d7e",
            }}
          >
            Commencer
          </Link>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section
        style={{
          position: "relative",
          overflow: "hidden",
          background: "linear-gradient(158deg, #2b2d7e 0%, #4648d4 58%, #5d60ea 100%)",
          color: "#fff",
          padding: "clamp(56px, 8vw, 96px) clamp(24px, 6vw, 84px) clamp(64px, 8vw, 104px)",
        }}
      >
        <div aria-hidden style={{ position: "absolute", top: -160, right: -120, width: 460, height: 460, borderRadius: "50%", background: "radial-gradient(circle, rgba(255,255,255,0.14) 0%, rgba(255,255,255,0) 65%)" }} />
        <div aria-hidden style={{ position: "absolute", bottom: -200, left: -160, width: 520, height: 520, borderRadius: "50%", background: "radial-gradient(circle, rgba(0,0,0,0.22) 0%, rgba(0,0,0,0) 65%)" }} />

        <div style={{ position: "relative", maxWidth: 1080, margin: "0 auto", textAlign: "center" }}>
          <h1 style={{ margin: 0, fontSize: "clamp(32px, 4.4vw, 56px)", lineHeight: 1.1, letterSpacing: "-0.028em" }}>
            Arrête de deviner<br />
            <span style={{ background: "linear-gradient(transparent 68%, rgba(255,255,255,0.32) 68%)" }}>ce qui marche</span> sur LinkedIn.
          </h1>

          <p style={{ margin: "22px auto 0", maxWidth: 620, fontSize: "clamp(15px, 1.5vw, 18px)", lineHeight: 1.6, opacity: 0.92 }}>
            Cibl décrypte les comptes qui performent dans ton marché, écrit tes posts dans ta voix
            à partir de ce qui marche vraiment, et te ramène les prospects qui commentent tes concurrents.
          </p>

          <div style={{ marginTop: 30, display: "flex", justifyContent: "center" }}>
            <StartButton light />
          </div>
          <p style={{ margin: "14px 0 0", fontSize: 13, opacity: 0.78 }}>
            Sans engagement · résiliable en un clic
          </p>

          {/* Preuve : tendances réellement mesurées par l'outil */}
          <div
            style={{
              margin: "44px auto 0",
              maxWidth: 720,
              padding: "18px 22px",
              borderRadius: 16,
              background: "rgba(255,255,255,0.09)",
              border: "1px solid rgba(255,255,255,0.18)",
              backdropFilter: "blur(4px)",
              textAlign: "left",
            }}
          >
            <p style={{ margin: "0 0 12px", fontSize: 11.5, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", opacity: 0.75, textAlign: "center" }}>
              Mesuré sur de vraies analyses — pas du feeling
            </p>
            <div className="lp-proof" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14 }}>
              {PROOF_STATS.map((stat) => (
                <div key={stat.text} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13.5 }}>
                  {stat.up ? (
                    <TrendingUp size={16} style={{ color: "#7ef0c0", flexShrink: 0 }} />
                  ) : (
                    <TrendingDown size={16} style={{ color: "#ffb4a8", flexShrink: 0 }} />
                  )}
                  <span style={{ opacity: 0.95 }}>{stat.text}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── Comment ça marche ── */}
      <section id="comment" style={{ padding: "clamp(56px, 7vw, 88px) clamp(24px, 6vw, 84px)" }}>
        <div style={{ maxWidth: 1080, margin: "0 auto" }}>
          <h2 style={{ margin: 0, fontSize: "clamp(24px, 2.8vw, 34px)", letterSpacing: "-0.02em", textAlign: "center" }}>
            Comment ça marche
          </h2>
          <p style={{ margin: "12px auto 0", maxWidth: 560, textAlign: "center", color: "var(--muted)", fontSize: 15, lineHeight: 1.6 }}>
            Quatre étapes, et la première prend une minute.
          </p>

          <ol className="lp-steps" style={{ listStyle: "none", padding: 0, margin: "44px 0 0", display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 22 }}>
            {STEPS.map((step) => (
              <li key={step.n}>
                <span style={{ fontSize: 13, fontWeight: 800, letterSpacing: "0.08em", color: "var(--primary)" }}>{step.n}</span>
                <h3 style={{ margin: "10px 0 8px", fontSize: 17, letterSpacing: "-0.01em" }}>{step.title}</h3>
                <p style={{ margin: 0, fontSize: 14, lineHeight: 1.6, color: "var(--muted)" }}>{step.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ── Fonctionnalités ── */}
      <section
        id="fonctionnalites"
        style={{
          padding: "clamp(56px, 7vw, 88px) clamp(24px, 6vw, 84px)",
          background: "radial-gradient(circle at 80% 0%, rgba(70,72,212,0.06) 0%, rgba(70,72,212,0) 45%), var(--surface)",
        }}
      >
        <div style={{ maxWidth: 1080, margin: "0 auto" }}>
          <h2 style={{ margin: 0, fontSize: "clamp(24px, 2.8vw, 34px)", letterSpacing: "-0.02em", textAlign: "center" }}>
            Tout est dans l'app
          </h2>
          <p style={{ margin: "12px auto 0", maxWidth: 560, textAlign: "center", color: "var(--muted)", fontSize: 15, lineHeight: 1.6 }}>
            De l'analyse du marché au prospect qui répond, sans changer d'outil.
          </p>

          <div className="lp-features" style={{ margin: "44px 0 0", display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 18 }}>
            {FEATURES.map((f) => (
              <div
                key={f.title}
                style={{
                  padding: 22,
                  borderRadius: 14,
                  background: "var(--surface-low)",
                  border: "1px solid var(--border)",
                }}
              >
                <span
                  style={{
                    display: "grid",
                    placeItems: "center",
                    width: 38,
                    height: 38,
                    borderRadius: 10,
                    color: "var(--primary)",
                    background: "rgba(70,72,212,0.08)",
                    border: "1px solid rgba(70,72,212,0.18)",
                  }}
                >
                  {f.icon}
                </span>
                <h3 style={{ margin: "14px 0 8px", fontSize: 16, letterSpacing: "-0.01em" }}>{f.title}</h3>
                <p style={{ margin: 0, fontSize: 14, lineHeight: 1.6, color: "var(--muted)" }}>{f.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Tarif ── */}
      <section id="tarif" style={{ padding: "clamp(56px, 7vw, 88px) clamp(24px, 6vw, 84px)" }}>
        <div
          style={{
            maxWidth: 560,
            margin: "0 auto",
            padding: "36px 32px",
            borderRadius: 18,
            background: "var(--surface)",
            border: "1px solid var(--border)",
            textAlign: "center",
          }}
        >
          <span
            style={{
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
            <Target size={12} /> Abonnement Cibl
          </span>

          <div style={{ marginTop: 18, display: "flex", alignItems: "baseline", justifyContent: "center", gap: 8 }}>
            <span style={{ fontSize: 46, fontWeight: 800, letterSpacing: "-0.025em" }}>{price}</span>
            <span style={{ fontSize: 16, color: "var(--muted)" }}>/ mois</span>
          </div>
          <p style={{ margin: "8px 0 0", fontSize: 14.5, color: "var(--muted)" }}>
            {credits.toLocaleString("fr-FR")} crédits rechargés chaque mois · sans engagement · résiliable en un clic
          </p>

          <ul style={{ listStyle: "none", padding: 0, margin: "26px 0 0", display: "grid", gap: 11, textAlign: "left" }}>
            {FEATURES.map((f) => (
              <li key={f.title} style={{ display: "flex", gap: 10, alignItems: "center", fontSize: 14.5 }}>
                <CheckCircle2 size={15} style={{ color: "var(--primary)", flexShrink: 0 }} />
                <span>{f.title}</span>
              </li>
            ))}
          </ul>

          <div style={{ marginTop: 28, display: "flex", justifyContent: "center" }}>
            <StartButton />
          </div>
        </div>
      </section>

      {/* ── CTA final ── */}
      <section
        style={{
          position: "relative",
          overflow: "hidden",
          background: "linear-gradient(158deg, #2b2d7e 0%, #4648d4 58%, #5d60ea 100%)",
          color: "#fff",
          padding: "clamp(56px, 7vw, 88px) clamp(24px, 6vw, 84px)",
          textAlign: "center",
        }}
      >
        <div aria-hidden style={{ position: "absolute", top: -140, left: "50%", width: 460, height: 460, marginLeft: -230, borderRadius: "50%", background: "radial-gradient(circle, rgba(255,255,255,0.12) 0%, rgba(255,255,255,0) 65%)" }} />
        <div style={{ position: "relative" }}>
          <h2 style={{ margin: 0, fontSize: "clamp(24px, 3vw, 38px)", letterSpacing: "-0.024em" }}>
            Ton prochain post, écrit à partir de ce qui marche.
          </h2>
          <p style={{ margin: "14px auto 0", maxWidth: 520, fontSize: 15.5, lineHeight: 1.6, opacity: 0.9 }}>
            Colle ton profil LinkedIn, réponds à quelques questions, et regarde ce que ça donne.
          </p>
          <div style={{ marginTop: 28, display: "flex", justifyContent: "center" }}>
            <StartButton light />
          </div>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer
        style={{
          padding: "32px clamp(24px, 6vw, 84px)",
          borderTop: "1px solid var(--border)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ display: "grid", placeItems: "center", width: 28, height: 28, borderRadius: 8, color: "var(--primary)", background: "rgba(70,72,212,0.08)", border: "1px solid rgba(70,72,212,0.18)" }}>
            <Target size={15} />
          </span>
          <span style={{ fontSize: 13.5, color: "var(--muted)" }}>
            Cibl — © {new Date().getFullYear()}
          </span>
        </div>
        <p style={{ margin: 0, fontSize: 12.5, color: "var(--muted)", display: "flex", alignItems: "center", gap: 6 }}>
          <Lock size={13} /> Paiement sécurisé par Stripe — ta carte est gérée par Stripe, jamais par nous.
        </p>
      </footer>

      <style>{`
        .lp-navlink {
          color: rgba(255,255,255,0.85);
          text-decoration: none;
          font-size: 14px;
          font-weight: 500;
        }
        .lp-navlink:hover { color: #fff; }
        @media (max-width: 900px) {
          .lp-steps { grid-template-columns: repeat(2, 1fr) !important; }
          .lp-features { grid-template-columns: repeat(2, 1fr) !important; }
          .lp-proof { grid-template-columns: 1fr !important; }
        }
        @media (max-width: 640px) {
          .lp-steps { grid-template-columns: 1fr !important; }
          .lp-features { grid-template-columns: 1fr !important; }
          .lp-navlink { display: none; }
        }
      `}</style>
    </main>
  );
}

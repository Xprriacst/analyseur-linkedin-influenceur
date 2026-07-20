"use client";

/**
 * Landing publique (/offre) — la page de vente.
 *
 * Elle ne fait qu'UNE chose : amener sur /start (le parcours guidé qui analyse,
 * questionne, crée le compte puis encaisse). Aucun formulaire ici : on ne demande
 * ni e-mail ni carte avant d'avoir montré le travail fait.
 *
 * Preuve affichée dans le hero : le volume analysé (INFLUENCERS_ANALYZED /
 * POSTS_ANALYZED), qui inclut le travail fait hors app par Alex. Pas de témoignages
 * tant qu'il n'y a pas de vraies citations de vrais clients.
 */

import { useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  BarChart3,
  ChevronDown,
  Flame,
  Inbox,
  Lightbulb,
  Lock,
  MessageSquare,
  PenLine,
  Radar,
  Search,
  Send,
  ShieldCheck,
  Target,
  Users,
} from "lucide-react";

// La landing ne montre AUCUN prix (décision produit) : le tarif n'apparaît qu'à
// l'écran de paiement (/start), une fois l'onboarding rempli. On garde seulement
// le cadrage « offre de lancement / N premiers clients », qui ne révèle pas de prix.
// ⚠️ Pas de compteur « il reste N places » : tant qu'il n'est pas branché sur le vrai
// nombre de clients, c'est un faux.
const LAUNCH_SEATS = 150;
// Volumes analysés — incluent le travail fait hors de l'app (autre outil). Faits
// constatés par Alex, pas des compteurs de la base ; à réviser à la main.
const INFLUENCERS_ANALYZED = 150;
const POSTS_ANALYZED = 3500;

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

/** Les 3 façons dont Cibl touche à LinkedIn — réponse type à la question « c'est safe ? ». */
const TRUST: { icon: React.ReactNode; title: string; method: string; body: string }[] = [
  {
    icon: <Search size={18} />,
    title: "Analyse",
    method: "Données publiques · zéro connexion",
    body: "Ton compte, les influenceurs de ton secteur, leurs meilleurs posts : on lit ce qui est public via un prestataire spécialisé. Aucune connexion à ton LinkedIn. Tu peux t'en servir seul, sans jamais activer la publication ni la prospection.",
  },
  {
    icon: <Send size={18} />,
    title: "Publication",
    method: "API officielle LinkedIn",
    body: "Quand tu publies ou programmes un post depuis Cibl, ça passe par l'API officielle LinkedIn. Conforme, traçable, sans script parallèle.",
  },
  {
    icon: <MessageSquare size={18} />,
    title: "Prospection",
    method: "Prestataire spécialisé · garde-fous",
    body: "Invitations, messages, signaux d'intention : LinkedIn ne propose pas d'API officielle pour ça. On passe par un prestataire spécialisé (pratique courante), avec plafonds jour/semaine, délais aléatoires, warm-up progressif, et pause auto au moindre signal d'alerte.",
  },
];

const FAQ: { q: string; a: string }[] = [
  {
    q: "Comment Cibl agit-il sur LinkedIn — API officielle, scripts, ou usage natif ?",
    a: "Ça dépend de l'action. L'analyse lit des données publiques sans se connecter à ton compte. La publication passe par l'API officielle LinkedIn. La prospection (invitations, messages) utilise un prestataire spécialisé — LinkedIn n'offre pas d'API officielle pour ça — avec des garde-fous stricts (plafonds, délais aléatoires, warm-up, pause auto).",
  },
  {
    q: "Est-ce que je dois connecter mon compte LinkedIn pour commencer ?",
    a: "Non. Tu peux coller ton profil, recevoir ton analyse et t'inspirer des comptes qui performent sans jamais relier ton LinkedIn. La connexion ne devient utile que le jour où tu veux publier ou prospecter depuis l'app.",
  },
  {
    q: "Est-ce risqué pour mon compte ?",
    a: "L'analyse : zéro risque (pas de connexion). La publication : API officielle. La prospection : c'est le seul volet qui touche à ton compte en envoi — d'où les plafonds quotidiens/hebdo, le warm-up sur les comptes neufs, et l'arrêt automatique si LinkedIn signale une limite.",
  },
  {
    q: "Puis-je n'utiliser que l'analyse, sans prospection ?",
    a: "Oui. Beaucoup de clients s'en tiennent à la veille, au générateur et à la publication. La prospection s'active seulement si tu connectes ton compte pour ça, dans Mon profil.",
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

function FaqItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={"lp-faq-item" + (open ? " open" : "")}>
      <button
        type="button"
        className="lp-faq-q"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span>{q}</span>
        <ChevronDown size={18} className="lp-faq-chevron" />
      </button>
      {open && <p className="lp-faq-a">{a}</p>}
    </div>
  );
}

export default function OffrePage() {
  // Aucun appel /billing/plan ici : la landing ne montre pas de prix. Le tarif est
  // lu depuis Stripe sur /start, à l'écran de paiement.
  return (
    <main className="lp">
      {/* ── Barre de navigation ── */}
      <nav className="lp-nav">
        <Link href="/offre" className="lp-brand">
          <span className="lp-brand-mark">
            <Target size={17} />
          </span>
          <span className="lp-brand-name">Cibl</span>
        </Link>

        <div className="lp-nav-actions">
          <a href="#comment" className="lp-navlink lp-navlink-anchor">Comment ça marche</a>
          <a href="#fonctionnalites" className="lp-navlink lp-navlink-anchor">Fonctionnalités</a>
          <a href="#securite" className="lp-navlink lp-navlink-anchor">Sécurité</a>
          <a href="#faq" className="lp-navlink lp-navlink-anchor">FAQ</a>
          <Link href="/" className="lp-navlink lp-navlink-login">Se connecter</Link>
          <Link href="/start" className="lp-nav-cta">
            Commencer
          </Link>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section className="lp-hero-section">
        <div aria-hidden className="lp-blob lp-blob-a" />
        <div aria-hidden className="lp-blob lp-blob-b" />

        {/* Hero en deux colonnes : promesse à gauche, mockup Mac à droite. */}
        <div className="lp-hero">
          {/* ── Colonne gauche : le texte ── */}
          <div className="lp-hero-text">
            <span className="lp-badge">
              <Flame size={14} /> Offre de lancement — {LAUNCH_SEATS} premiers clients
            </span>

            <h1 className="lp-hero-title">
              Arrête de deviner{" "}
              <span className="lp-hero-highlight">ce qui marche</span> sur LinkedIn.
            </h1>

            <p className="lp-hero-lead">
              Cibl décrypte les comptes qui performent dans ton marché, écrit tes posts dans ta voix
              à partir de ce qui marche vraiment, et te ramène les prospects qui commentent tes concurrents.
            </p>

            <div className="lp-hero-cta">
              <StartButton light />
              <span className="lp-hero-note">Sans engagement · résiliable en un clic</span>
            </div>

            {/* Preuve : le volume analysé, en deux chiffres. */}
            <div className="lp-proof">
              <div>
                <div className="lp-proof-num">{INFLUENCERS_ANALYZED}+</div>
                <div className="lp-proof-label">influenceurs analysés</div>
              </div>
              <div>
                <div className="lp-proof-num">{POSTS_ANALYZED.toLocaleString("fr-FR")}+</div>
                <div className="lp-proof-label">posts analysés</div>
              </div>
            </div>
          </div>

          {/* ── Colonne droite : le mockup MacBook ── */}
          <div className="lp-hero-mac">
            <div className="lp-mac-screen">
              {/* Encoche caméra */}
              <div aria-hidden className="lp-mac-camera">
                <span />
              </div>
              <img
                src="/app-preview.png"
                alt="L'application Cibl : le générateur de posts, la veille et la prospection dans une seule interface."
                className="lp-mac-img"
              />
            </div>
            {/* Socle contenu dans le wrapper (overflow clip) pour ne jamais déborder. */}
            <div aria-hidden className="lp-mac-stand">
              <div className="lp-mac-hinge" />
            </div>
          </div>
        </div>
      </section>

      {/* ── Comment ça marche ── */}
      <section id="comment" className="lp-section">
        <div className="lp-section-inner">
          <h2 className="lp-section-title">Comment ça marche</h2>
          <p className="lp-section-desc">
            Quatre étapes, et la première prend une minute.
          </p>

          <ol className="lp-steps">
            {STEPS.map((step) => (
              <li key={step.n}>
                <span className="lp-step-n">{step.n}</span>
                <h3 className="lp-step-title">{step.title}</h3>
                <p className="lp-step-body">{step.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ── Fonctionnalités ── */}
      <section id="fonctionnalites" className="lp-section lp-section-alt">
        <div className="lp-section-inner">
          <h2 className="lp-section-title">Tout est dans l&apos;app</h2>
          <p className="lp-section-desc">
            De l&apos;analyse du marché au prospect qui répond, sans changer d&apos;outil.
          </p>

          <div className="lp-features">
            {FEATURES.map((f) => (
              <div key={f.title} className="lp-feature">
                <span className="lp-feature-icon">{f.icon}</span>
                <h3 className="lp-feature-title">{f.title}</h3>
                <p className="lp-feature-body">{f.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Sécurité LinkedIn ── */}
      <section id="securite" className="lp-section">
        <div className="lp-section-inner">
          <div className="lp-trust-eyebrow">
            <ShieldCheck size={16} /> Comment on touche à ton LinkedIn
          </div>
          <h2 className="lp-section-title">Trois actions, trois niveaux de risque</h2>
          <p className="lp-section-desc">
            On ne mélange pas analyse, publication et prospection. Chaque brique a son canal — et tu actives seulement ce dont tu as besoin.
          </p>

          <div className="lp-trust">
            {TRUST.map((t) => (
              <div key={t.title} className="lp-trust-card">
                <span className="lp-feature-icon">{t.icon}</span>
                <h3 className="lp-feature-title">{t.title}</h3>
                <div className="lp-trust-method">{t.method}</div>
                <p className="lp-feature-body">{t.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── FAQ ── */}
      <section id="faq" className="lp-section lp-section-alt">
        <div className="lp-section-inner lp-faq-inner">
          <h2 className="lp-section-title">Questions fréquentes</h2>
          <p className="lp-section-desc">
            La question qu&apos;on nous pose le plus — et ce qu&apos;il faut savoir avant de commencer.
          </p>
          <div className="lp-faq">
            {FAQ.map((item) => (
              <FaqItem key={item.q} q={item.q} a={item.a} />
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA final ── */}
      <section className="lp-cta">
        <div aria-hidden className="lp-blob lp-blob-c" />
        <div className="lp-cta-inner">
          <h2 className="lp-cta-title">
            Ton prochain post, écrit à partir de ce qui marche.
          </h2>
          <p className="lp-cta-desc">
            Colle ton profil LinkedIn : tu reçois ton analyse avant même de créer un compte.
          </p>
          <div className="lp-cta-btn">
            <StartButton light />
          </div>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="lp-footer">
        <div className="lp-footer-brand">
          <span className="lp-footer-mark">
            <Target size={15} />
          </span>
          <span>Cibl — © {new Date().getFullYear()}</span>
        </div>
        <p className="lp-footer-secure">
          <Lock size={13} className="lp-footer-lock" />
          <span>Paiement sécurisé par Stripe — ta carte est gérée par Stripe, jamais par nous.</span>
        </p>
      </footer>

      <style>{`
        .lp {
          background: var(--surface-low);
          overflow-x: clip;
          min-width: 0;
        }

        /* ── Nav ── */
        .lp-nav {
          position: sticky;
          top: 0;
          z-index: 10;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          padding: 14px clamp(16px, 5vw, 56px);
          background: rgba(43,45,126,0.92);
          backdrop-filter: blur(8px);
          color: #fff;
        }
        .lp-brand {
          display: flex;
          align-items: center;
          gap: 10px;
          color: #fff;
          text-decoration: none;
          flex-shrink: 0;
        }
        .lp-brand-mark {
          display: grid;
          place-items: center;
          width: 32px;
          height: 32px;
          border-radius: 10px;
          background: rgba(255,255,255,0.16);
          border: 1px solid rgba(255,255,255,0.25);
        }
        .lp-brand-name {
          font-size: 16px;
          font-weight: 800;
          letter-spacing: 0.06em;
        }
        .lp-nav-actions {
          display: flex;
          align-items: center;
          justify-content: flex-end;
          gap: clamp(10px, 2.2vw, 22px);
          min-width: 0;
          flex-wrap: nowrap;
        }
        .lp-navlink {
          color: rgba(255,255,255,0.85);
          text-decoration: none;
          font-size: 14px;
          font-weight: 500;
          white-space: nowrap;
        }
        .lp-navlink:hover { color: #fff; }
        .lp-nav-cta {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          height: 38px;
          padding: 0 16px;
          border-radius: 10px;
          font-size: 14px;
          font-weight: 700;
          text-decoration: none;
          background: #fff;
          color: #2b2d7e;
          flex-shrink: 0;
          white-space: nowrap;
        }

        /* ── Hero ── */
        .lp-hero-section {
          position: relative;
          overflow: hidden;
          background: linear-gradient(158deg, #2b2d7e 0%, #4648d4 58%, #5d60ea 100%);
          color: #fff;
          padding: clamp(40px, 8vw, 96px) clamp(16px, 6vw, 84px) clamp(48px, 8vw, 104px);
        }
        .lp-blob {
          position: absolute;
          border-radius: 50%;
          pointer-events: none;
        }
        .lp-blob-a {
          top: -160px;
          right: -120px;
          width: min(460px, 70vw);
          height: min(460px, 70vw);
          background: radial-gradient(circle, rgba(255,255,255,0.14) 0%, rgba(255,255,255,0) 65%);
        }
        .lp-blob-b {
          bottom: -200px;
          left: -160px;
          width: min(520px, 80vw);
          height: min(520px, 80vw);
          background: radial-gradient(circle, rgba(0,0,0,0.22) 0%, rgba(0,0,0,0) 65%);
        }
        .lp-blob-c {
          top: -140px;
          left: 50%;
          width: min(460px, 90vw);
          height: min(460px, 90vw);
          transform: translateX(-50%);
          background: radial-gradient(circle, rgba(255,255,255,0.12) 0%, rgba(255,255,255,0) 65%);
        }
        .lp-hero {
          position: relative;
          max-width: 1180px;
          margin: 0 auto;
          display: grid;
          grid-template-columns: minmax(0, 1fr) minmax(0, 1.05fr);
          align-items: center;
          gap: clamp(28px, 5vw, 64px);
          min-width: 0;
        }
        .lp-hero-text { min-width: 0; }
        .lp-badge {
          display: inline-flex;
          align-items: center;
          gap: 7px;
          margin-bottom: 22px;
          padding: 6px 14px;
          border-radius: 20px;
          font-size: 13px;
          font-weight: 700;
          background: rgba(255,255,255,0.14);
          border: 1px solid rgba(255,255,255,0.28);
          max-width: 100%;
          box-sizing: border-box;
        }
        .lp-hero-title {
          margin: 0;
          font-size: clamp(28px, 4.2vw, 50px);
          line-height: 1.12;
          letter-spacing: -0.028em;
          overflow-wrap: anywhere;
        }
        .lp-hero-highlight {
          background: linear-gradient(transparent 68%, rgba(255,255,255,0.32) 68%);
        }
        .lp-hero-lead {
          margin: 22px 0 0;
          max-width: 520px;
          font-size: clamp(15px, 1.4vw, 17px);
          line-height: 1.6;
          opacity: 0.92;
        }
        .lp-hero-cta {
          margin-top: 30px;
          display: flex;
          align-items: center;
          gap: 16px;
          flex-wrap: wrap;
        }
        .lp-hero-note { font-size: 13px; opacity: 0.78; }
        .lp-proof {
          margin: 36px 0 0;
          max-width: 460px;
          padding: 20px 22px;
          border-radius: 16px;
          background: rgba(255,255,255,0.09);
          border: 1px solid rgba(255,255,255,0.18);
          backdrop-filter: blur(4px);
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 18px;
        }
        .lp-proof-num {
          font-size: clamp(26px, 6vw, 32px);
          font-weight: 800;
          letter-spacing: -0.02em;
        }
        .lp-proof-label {
          font-size: 13px;
          opacity: 0.82;
          margin-top: 3px;
        }

        /* Mockup Mac — le wrapper clippe le socle plus large */
        .lp-hero-mac {
          width: 100%;
          max-width: 620px;
          min-width: 0;
          justify-self: stretch;
          overflow: hidden;
          padding: 0 2%;
          box-sizing: border-box;
        }
        .lp-mac-screen {
          padding: 10px 10px 8px;
          border-radius: 14px;
          background: linear-gradient(180deg, #2f3040 0%, #1c1d28 100%);
          box-shadow: 0 30px 70px rgba(0,0,0,0.42), 0 0 0 1px rgba(255,255,255,0.09);
        }
        .lp-mac-camera {
          display: flex;
          justify-content: center;
          margin-bottom: 6px;
        }
        .lp-mac-camera span {
          width: 5px;
          height: 5px;
          border-radius: 50%;
          background: rgba(255,255,255,0.22);
        }
        .lp-mac-img {
          display: block;
          width: 100%;
          height: auto;
          border-radius: 6px;
          background: #fff;
        }
        .lp-mac-stand {
          width: 108%;
          margin-left: -4%;
          height: 13px;
          border-radius: 0 0 12px 12px;
          background: linear-gradient(180deg, #c9ccd6 0%, #8f93a4 62%, #6c7080 100%);
          box-shadow: 0 12px 26px rgba(0,0,0,0.34);
        }
        .lp-mac-hinge {
          width: 84px;
          height: 4px;
          margin: 0 auto;
          border-radius: 0 0 5px 5px;
          background: rgba(0,0,0,0.22);
        }

        /* ── Sections ── */
        .lp-section {
          padding: clamp(48px, 7vw, 88px) clamp(16px, 6vw, 84px);
        }
        .lp-section-alt {
          background:
            radial-gradient(circle at 80% 0%, rgba(70,72,212,0.06) 0%, rgba(70,72,212,0) 45%),
            var(--surface);
        }
        .lp-section-inner {
          max-width: 1080px;
          margin: 0 auto;
          text-align: center;
        }
        .lp-section-inner .lp-steps,
        .lp-section-inner .lp-features,
        .lp-section-inner .lp-trust,
        .lp-section-inner .lp-faq { text-align: left; }
        .lp-section-title {
          margin: 0;
          font-size: clamp(24px, 2.8vw, 34px);
          letter-spacing: -0.02em;
          text-align: center;
        }
        .lp-section-desc {
          margin: 12px auto 0;
          max-width: 560px;
          text-align: center;
          color: var(--muted);
          font-size: 15px;
          line-height: 1.6;
        }
        .lp-steps {
          list-style: none;
          padding: 0;
          margin: 44px 0 0;
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 22px;
        }
        .lp-step-n {
          font-size: 13px;
          font-weight: 800;
          letter-spacing: 0.08em;
          color: var(--primary);
        }
        .lp-step-title {
          margin: 10px 0 8px;
          font-size: 17px;
          letter-spacing: -0.01em;
        }
        .lp-step-body {
          margin: 0;
          font-size: 14px;
          line-height: 1.6;
          color: var(--muted);
        }
        .lp-features {
          margin: 44px 0 0;
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 18px;
        }
        .lp-trust-eyebrow {
          display: inline-flex;
          align-items: center;
          gap: 7px;
          margin: 0 auto 14px;
          padding: 6px 12px;
          border-radius: 999px;
          font-size: 13px;
          font-weight: 600;
          color: var(--primary);
          background: rgba(70,72,212,0.08);
          border: 1px solid rgba(70,72,212,0.16);
        }
        .lp-trust {
          margin: 44px 0 0;
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 18px;
        }
        .lp-trust-card {
          padding: 22px;
          border-radius: 14px;
          background: var(--surface);
          border: 1px solid var(--border);
          min-width: 0;
        }
        .lp-trust-method {
          display: inline-block;
          margin: 0 0 10px;
          padding: 4px 10px;
          border-radius: 999px;
          font-size: 12px;
          font-weight: 600;
          color: var(--primary);
          background: rgba(70,72,212,0.08);
        }
        .lp-faq-inner { max-width: 720px; }
        .lp-faq {
          margin: 36px 0 0;
          display: flex;
          flex-direction: column;
          gap: 10px;
        }
        .lp-faq-item {
          border: 1px solid var(--border);
          border-radius: 14px;
          background: var(--surface-low);
          overflow: hidden;
        }
        .lp-faq-q {
          width: 100%;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 14px;
          padding: 16px 18px;
          border: none;
          background: transparent;
          text-align: left;
          font-size: 15px;
          font-weight: 600;
          color: var(--ink);
          cursor: pointer;
        }
        .lp-faq-chevron {
          flex-shrink: 0;
          color: var(--muted);
          transition: transform .18s ease;
        }
        .lp-faq-item.open .lp-faq-chevron { transform: rotate(180deg); color: var(--primary); }
        .lp-faq-a {
          margin: 0;
          padding: 0 18px 16px;
          font-size: 14.5px;
          line-height: 1.6;
          color: var(--muted);
        }
        .lp-feature {
          padding: 22px;
          border-radius: 14px;
          background: var(--surface-low);
          border: 1px solid var(--border);
          min-width: 0;
        }
        .lp-feature-icon {
          display: grid;
          place-items: center;
          width: 38px;
          height: 38px;
          border-radius: 10px;
          color: var(--primary);
          background: rgba(70,72,212,0.08);
          border: 1px solid rgba(70,72,212,0.18);
        }
        .lp-feature-title {
          margin: 14px 0 8px;
          font-size: 16px;
          letter-spacing: -0.01em;
        }
        .lp-feature-body {
          margin: 0;
          font-size: 14px;
          line-height: 1.6;
          color: var(--muted);
        }

        /* ── CTA + footer ── */
        .lp-cta {
          position: relative;
          overflow: hidden;
          background: linear-gradient(158deg, #2b2d7e 0%, #4648d4 58%, #5d60ea 100%);
          color: #fff;
          padding: clamp(48px, 7vw, 88px) clamp(16px, 6vw, 84px);
          text-align: center;
        }
        .lp-cta-inner { position: relative; }
        .lp-cta-title {
          margin: 0;
          font-size: clamp(22px, 3.4vw, 38px);
          letter-spacing: -0.024em;
          overflow-wrap: anywhere;
        }
        .lp-cta-desc {
          margin: 14px auto 0;
          max-width: 520px;
          font-size: 15.5px;
          line-height: 1.6;
          opacity: 0.9;
        }
        .lp-cta-btn {
          margin-top: 28px;
          display: flex;
          justify-content: center;
        }
        .lp-footer {
          padding: 28px clamp(16px, 6vw, 84px);
          border-top: 1px solid var(--border);
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 14px 24px;
          flex-wrap: wrap;
        }
        .lp-footer-brand {
          display: flex;
          align-items: center;
          gap: 10px;
          font-size: 13.5px;
          color: var(--muted);
        }
        .lp-footer-mark {
          display: grid;
          place-items: center;
          width: 28px;
          height: 28px;
          border-radius: 8px;
          color: var(--primary);
          background: rgba(70,72,212,0.08);
          border: 1px solid rgba(70,72,212,0.18);
          flex-shrink: 0;
        }
        .lp-footer-secure {
          margin: 0;
          font-size: 12.5px;
          color: var(--muted);
          display: flex;
          align-items: flex-start;
          gap: 6px;
          max-width: 420px;
          line-height: 1.45;
        }
        .lp-footer-lock { flex-shrink: 0; margin-top: 2px; }

        /* ── Breakpoints ── */
        @media (max-width: 980px) {
          .lp-navlink-anchor { display: none; }
          .lp-hero {
            grid-template-columns: 1fr;
            text-align: center;
          }
          .lp-hero-lead,
          .lp-proof { margin-left: auto; margin-right: auto; }
          .lp-hero-cta { justify-content: center; }
          .lp-badge { justify-content: center; }
          .lp-hero-mac { margin: 4px auto 0; }
          .lp-steps { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          .lp-features,
          .lp-trust { grid-template-columns: 1fr; }
        }
        @media (max-width: 640px) {
          .lp-nav { padding-top: 12px; padding-bottom: 12px; }
          .lp-navlink-login { font-size: 13px; }
          .lp-nav-cta { height: 36px; padding: 0 14px; font-size: 13px; }
          .lp-badge {
            font-size: 12px;
            padding: 6px 12px;
            text-align: left;
            white-space: normal;
            line-height: 1.35;
          }
          .lp-hero-cta { flex-direction: column; align-items: center; gap: 10px; }
          .lp-proof { padding: 16px 14px; gap: 12px; }
          .lp-steps,
          .lp-features,
          .lp-trust { grid-template-columns: 1fr; margin-top: 32px; }
          .lp-faq-q { font-size: 14px; padding: 14px 14px; }
          .lp-footer {
            flex-direction: column;
            align-items: flex-start;
          }
          .lp-footer-secure { max-width: none; }
        }
        @media (max-width: 380px) {
          .lp-brand-name { display: none; }
          .lp-nav-actions { gap: 8px; }
        }
      `}</style>
    </main>
  );
}

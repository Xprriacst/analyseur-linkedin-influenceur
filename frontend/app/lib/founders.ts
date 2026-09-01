/**
 * Engagements commerciaux du tunnel fondateurs (/founders + /essai).
 *
 * ⚠️ Ce ne sont pas des textes d'ambiance : chaque valeur ici est une PROMESSE
 * faite à un prospect, décidée par Alex le 2026-08-11 (inspiration : funnel
 * Catalog/zoomgtm). Les changer change ce qu'on doit tenir :
 *
 * - `FOUNDERS_MONTHLY_SEATS` : nombre de nouveaux comptes fondateurs qu'on
 *   s'engage à onboarder par mois. La limite est réelle — l'accompagnement du
 *   démarrage (connexion LinkedIn, ciblage) est encore supervisé à la main.
 *   L'augmenter quand la capacité suit, jamais l'inverse en silence.
 * - `FOUNDERS_GUARANTEE_DAYS` : « satisfait ou remboursé » sur le PREMIER mois
 *   payé, à compter de la fin de l'essai. ⚠️ Le remboursement est MANUEL (via
 *   le dashboard Stripe) — aucune automatisation ne l'honore à ta place.
 *
 * Les chiffres de preuve reprennent ceux de /paiement (faits constatés,
 * révisés à la main — ne pas inventer, ne pas arrondir vers le haut).
 */
export const FOUNDERS_MONTHLY_SEATS = 40;
export const FOUNDERS_GUARANTEE_DAYS = 30;

export const PROOF_INFLUENCERS_ANALYZED = 150;
export const PROOF_POSTS_ANALYZED = 3500;

/**
 * Remise fondateurs sur le PREMIER mois payé (après l'essai).
 * ⚠️ Affichée au closing — pour qu'elle soit réelle, un coupon Stripe
 * (ou un prix d'intro) doit l'honorer. Sinon c'est une promesse non tenue.
 */
export const FOUNDERS_FIRST_MONTH_OFF_PCT = 40;

/**
 * Témoignage fondateur affiché au closing du tunnel.
 * ⚠️ Citation réelle (ReShape / @reshape_music) — ne pas inventer ni paraphraser.
 */
export const FOUNDERS_TESTIMONIAL = {
  handle: "@reshape_music",
  name: "ReShape",
  url: "https://www.instagram.com/reshape_music/",
  avatar: "/proof/reshape-music.png",
  quote: "oui le service est toop, on a passé les 4k merci les gars !!!",
} as const;

/**
 * Verbatims clients de la page de vente (`/offre`).
 * ⚠️ Citations réelles, collées telles quelles — ne pas inventer de rôle,
 * d'entreprise, de photo ni paraphraser.
 */
export const CLIENT_TESTIMONIALS = [
  {
    name: "Sacha",
    quote:
      "Pour être honnête avec vous les gars je suis 100% satisfait de votre accompagnement",
  },
  {
    name: "Joëlle",
    quote:
      "Je tenais d’abord à vous dire que je suis très contente de ce premier mois de collaboration. J’apprécie la qualité de votre travail, votre disponibilité et votre réactivité",
  },
] as const;

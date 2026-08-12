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
export const FOUNDERS_MONTHLY_SEATS = 20;
export const FOUNDERS_GUARANTEE_DAYS = 30;

export const PROOF_INFLUENCERS_ANALYZED = 150;
export const PROOF_POSTS_ANALYZED = 3500;

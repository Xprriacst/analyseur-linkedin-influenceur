import type { NextConfig } from "next";

/**
 * Anciennes portes d'entrée → `/pilote`, seule landing depuis le 2026-09-03.
 *
 * Décision d'Alex : une seule porte. Les pages restent dans le dépôt (elles ne
 * sont plus atteignables, pas supprimées) — revenir en arrière, c'est retirer
 * une ligne ici, pas ressusciter du code.
 *
 * ⚠️ `permanent: false` (307) VOLONTAIREMENT, pas 308 : une redirection
 * permanente est mise en cache par le navigateur du visiteur et survit au
 * retour arrière côté serveur. Sur des URI de campagne qu'on peut vouloir
 * rouvrir, c'est un aller sans retour pour tous ceux qui les ont déjà ouvertes.
 *
 * ⚠️ Ce que ça coûte, en connaissance de cause : `/start` était le tunnel
 * d'audit gratuit qui finissait sur le Calendly de Tom, et `/essai` le filet
 * des comptes non éligibles à l'essai. Les deux deviennent inatteignables.
 * (Le seul lien interne vers `/essai` venait de `/onboarding`, lui aussi
 * redirigé : personne ne se retrouve dans une impasse.)
 *
 * `/a/{token}` (page publique d'un audit déjà envoyé) et `/paiement` ne sont
 * PAS touchées : ce sont des liens déjà en circulation chez des prospects.
 */
const LEGACY_ENTRYPOINTS = ["/onboarding", "/founders", "/start", "/essai", "/offre"];

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async redirects() {
    return LEGACY_ENTRYPOINTS.map((source) => ({
      source,
      destination: "/pilote",
      permanent: false,
    }));
  },
};

export default nextConfig;

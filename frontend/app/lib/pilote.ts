/**
 * Copy et promesses de la landing `/pilote` (mode Pilote gratuit).
 *
 * Ce ne sont pas des textes d'ambiance. Les quotas 1 post / 3 contacts
 * sont ceux du ticket quotas ; le groupe privé est un accès Skool hors Cibl
 * (jamais « communauté Cibl », aucun chiffre d'inscrits inventé).
 */
export const PILOTE_POSTS_PER_DAY = 1;
export const PILOTE_CONTACTS_PER_DAY = 3;

export const PILOTE_GROUP_BLURB =
  "groupe privé de missions et de stratégies d'acquisition";

/** Fenêtre pendant laquelle un retour OAuth Google est traité comme une inscription, pas une reconnexion. */
export const FRESH_ACCOUNT_MS = 10 * 60 * 1000;

/** Compte créé à l'instant (retour Google) vs compte déjà existant qui se reconnecte. */
export function isFreshAccount(createdAt: string | undefined, now = Date.now()): boolean {
  const created = Date.parse(createdAt || "");
  return Number.isFinite(created) && now - created < FRESH_ACCOUNT_MS;
}

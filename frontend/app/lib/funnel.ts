/**
 * Funnel des landings publiques : ce qui permet de comparer « combien ouvrent
 * la page » à « combien créent un compte ».
 *
 * Deux moitiés, volontairement séparées :
 *  - la VUE part au serveur (`POST /{landing}/page-view`, anonyme) et atterrit
 *    dans `onboarding_preview_events` ;
 *  - le COMPTE se marque à l'inscription dans les métadonnées du compte
 *    (`landing`), lisible ensuite en SQL sur `auth.users`.
 *
 * Compter les comptes par leur seule date de création (« tout ce qui s'inscrit
 * depuis le lancement ») serait faux dès qu'une autre porte d'entrée est
 * rouverte, ou qu'un compte de test est créé — et faux sans que rien ne le
 * signale. D'où le marquage explicite.
 */

const DIRECT_API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL || "https://analyseur-linkedin-influenceur-api-eu.onrender.com";

/** Valeur écrite dans les métadonnées du compte à l'inscription depuis /pilote. */
export const PILOTE_LANDING = "pilote";

/**
 * Une vue par chargement de page, pas par rendu.
 *
 * Sans ce garde, un remontage du composant (StrictMode en dev, un changement
 * d'état qui remonte l'arbre en prod) recompterait le même visiteur : le
 * compteur gonflerait tout seul et le taux de conversion s'effondrerait sans
 * qu'aucune vraie visite ait bougé.
 */
const sent = new Set<string>();

/** Journalise l'ouverture d'une landing. Best-effort : ne lève jamais, n'attend rien. */
export function trackLandingPageView(landing: string): void {
  if (typeof window === "undefined" || sent.has(landing)) return;
  sent.add(landing);
  fetch(`${DIRECT_API_URL}/${landing}/page-view`, { method: "POST" }).catch(() => {
    /* ignore — un compteur qui rate une vue ne doit jamais se voir */
  });
}

/** Ouverture de la landing `/pilote` (mode Pilote gratuit). */
export function trackPilotePageView(): void {
  trackLandingPageView(PILOTE_LANDING);
}

/**
 * Métadonnées à passer à `supabase.auth.signUp({ options: { data } })` depuis
 * la landing `/pilote`, pour que le compte créé soit rattachable à sa landing.
 *
 * ⚠️ Ces métadonnées vivent dans `user_metadata`, que l'utilisateur peut
 * MODIFIER lui-même depuis son navigateur (`supabase.auth.updateUser`). C'est
 * acceptable pour un compteur interne — personne n'a intérêt à truquer son
 * propre canal d'acquisition — mais `landing` ne doit JAMAIS servir à ouvrir un
 * droit (quota, feature, plan gratuit) : ces décisions se prennent dans
 * `app_metadata`, côté serveur, comme le rôle et les feature flags.
 */
export function piloteSignupMetadata(
  extra: Record<string, unknown> = {}
): Record<string, unknown> {
  return { ...extra, landing: PILOTE_LANDING };
}

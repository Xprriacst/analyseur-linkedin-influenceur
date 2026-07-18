/**
 * Analytics first-party via Plausible (sans cookies, pas de bandeau RGPD).
 *
 * Activé seulement si NEXT_PUBLIC_PLAUSIBLE_DOMAIN est défini (build Netlify).
 * Absent en local ⇒ no-op, zéro requête réseau.
 */

export type PlausibleProps = Record<string, string | number | boolean>;

type PlausibleFn = {
  (event: string, options?: { u?: string; props?: PlausibleProps }): void;
  q?: unknown[][];
};

declare global {
  interface Window {
    plausible?: PlausibleFn;
  }
}

/** Domaine Plausible (ex. lkd-outreach.netlify.app). Vide = analytics off. */
export function analyticsDomain(): string {
  return (process.env.NEXT_PUBLIC_PLAUSIBLE_DOMAIN || "").trim();
}

export function analyticsEnabled(): boolean {
  return Boolean(analyticsDomain());
}

/** Initialise la file d'attente pour que les events partent même avant le script. */
export function ensurePlausibleQueue(): void {
  if (typeof window === "undefined") return;
  if (typeof window.plausible === "function") return;
  const queue: PlausibleFn = function (
    this: void,
    ...args: [string, { u?: string; props?: PlausibleProps }?]
  ) {
    queue.q = queue.q || [];
    queue.q.push(args);
  };
  window.plausible = queue;
}

/** Pageview manuelle (App Router : les navigations client ne rechargent pas le script). */
export function trackPageview(url: string): void {
  if (!analyticsEnabled() || typeof window === "undefined") return;
  ensurePlausibleQueue();
  window.plausible?.("pageview", { u: url });
}

/** Événement custom (goals Plausible : créés auto au premier envoi). */
export function trackEvent(name: string, props?: PlausibleProps): void {
  if (!analyticsEnabled() || typeof window === "undefined") return;
  ensurePlausibleQueue();
  window.plausible?.(name, props ? { props } : undefined);
}

"use client";

/**
 * Charge Plausible et envoie un pageview à chaque navigation App Router.
 * Rendu null si NEXT_PUBLIC_PLAUSIBLE_DOMAIN est absent.
 */

import { Suspense, useEffect } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import Script from "next/script";
import {
  analyticsDomain,
  analyticsEnabled,
  ensurePlausibleQueue,
  trackPageview,
} from "../lib/analytics";

function PlausiblePageviews() {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (!analyticsEnabled()) return;
    ensurePlausibleQueue();
    const qs = searchParams?.toString();
    const path = pathname + (qs ? `?${qs}` : "");
    trackPageview(window.location.origin + path);
  }, [pathname, searchParams]);

  return null;
}

export default function Analytics() {
  const domain = analyticsDomain();
  if (!domain) return null;

  return (
    <>
      <Script
        defer
        data-domain={domain}
        src="https://plausible.io/js/script.manual.js"
        strategy="afterInteractive"
      />
      {/* useSearchParams exige un Suspense boundary (Next App Router). */}
      <Suspense fallback={null}>
        <PlausiblePageviews />
      </Suspense>
    </>
  );
}

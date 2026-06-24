import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "LKD Outreach",
};

/**
 * Shared layout for all authenticated app routes.
 * Provides the sidebar + main content shell (ALE-82 Phase 0).
 *
 * During migration from page.tsx monolith, this layout is a skeleton.
 * Views will be moved here progressively: /veille, /contenu, /profil, /assistant.
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

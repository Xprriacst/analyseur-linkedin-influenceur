"use client";

import { Compass, Lock, UserRound, Users, Zap } from "lucide-react";

export type PilotNavTab = "today" | "profile";

type PilotNavProps = {
  activeTab: PilotNavTab;
  onTabChange: (tab: PilotNavTab) => void;
  onUpgrade: () => void;
  upgradeBusy?: boolean;
  /** Pastilles futures (posts, leads, missions) — réservé phase 2. */
  badges?: { posts?: number; leads?: number; group?: number };
};

export function PilotNav({
  activeTab,
  onTabChange,
  onUpgrade,
  upgradeBusy = false,
  badges,
}: PilotNavProps) {
  return (
    <nav className="pilot-nav" aria-label="Navigation Mode Pilote">
      <div className="pilot-nav-brand">
        <span className="pilot-nav-mark" aria-hidden="true" />
        <span className="pilot-nav-title">
          Cibl
          <span className="pilot-nav-beta">Pilote</span>
        </span>
      </div>

      <div className="pilot-nav-items">
        <button
          type="button"
          className={`pilot-nav-item${activeTab === "today" ? " active" : ""}`}
          onClick={() => onTabChange("today")}
        >
          <Compass size={18} aria-hidden="true" />
          <span>Vue pilote</span>
          {badges?.posts ? (
            <span className="pilot-nav-badge" aria-label={`${badges.posts} nouveauté(s)`}>
              {badges.posts}
            </span>
          ) : null}
        </button>
        <button
          type="button"
          className={`pilot-nav-item${activeTab === "profile" ? " active" : ""}`}
          onClick={() => onTabChange("profile")}
        >
          <UserRound size={18} aria-hidden="true" />
          <span>Mon profil</span>
        </button>
        <button
          type="button"
          className="pilot-nav-item pilot-nav-item-locked"
          disabled
          title="Réservé aux abonnés premium"
        >
          <Users size={18} aria-hidden="true" />
          <span>Groupe privé</span>
          <Lock size={14} className="pilot-nav-lock" aria-hidden="true" />
          {badges?.group ? (
            <span className="pilot-nav-badge" aria-label={`${badges.group} mission(s)`}>
              {badges.group}
            </span>
          ) : null}
        </button>
      </div>

      {/* Plus d'entrée « Mode Expert » ici : le Mode Pilote est la seule vue
          proposée tant que le compte n'est pas premium. L'aperçu Expert reste
          atteignable par les actions qui en ont besoin (Générateur, Agent IA),
          et son bandeau porte le retour au Mode Pilote. */}
      <div className="pilot-nav-footer">
        <button
          type="button"
          className="pilot-nav-upgrade"
          onClick={onUpgrade}
          disabled={upgradeBusy}
        >
          <Zap size={16} aria-hidden="true" />
          {upgradeBusy ? "Redirection…" : "Passer en premium"}
        </button>
      </div>
    </nav>
  );
}

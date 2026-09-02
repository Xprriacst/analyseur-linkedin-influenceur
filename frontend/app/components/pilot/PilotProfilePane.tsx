"use client";

import { Check, Loader2, LogOut, Target, UserPlus, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { authHeaders } from "../../lib/supabase";
import type { PilotFollowSuggestion, PilotStrategy } from "./PilotModeView";

const DIRECT_API_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  "https://analyseur-linkedin-influenceur-api-eu.onrender.com";

type ProfileDraft = {
  display_name?: string;
  brand_name?: string;
  target_audience?: string;
  core_offer?: string;
  business_description?: string;
};

type PilotProfilePaneProps = {
  onRequireAuth?: () => void;
  /** Compte connecté — le Mode Pilote n'a pas d'entête, c'est ici qu'on le voit. */
  userEmail?: string;
  onSignOut?: () => void;
  /** Stratégie du plan du jour — déjà chargée par le shell, rien à refetcher. */
  strategy?: PilotStrategy | null;
  // Suggestions « à suivre » : le shell les charge à la PREMIÈRE ouverture de
  // cet onglet, jamais au chargement de la vue pilote (le cache mutualisé n'a
  // pas à être relu tous les jours pour un panneau que peu de gens ouvrent).
  followSuggestions?: PilotFollowSuggestion[];
  followLoading?: boolean;
  followError?: string;
  followedHandles?: string[];
  followCapReached?: boolean;
  onFollowPanelOpen?: () => void;
  onFollowProfile?: (handle: string) => void;
};

/** Initiales d'un nom — les suggestions arrivent du serveur sans champ `initials`. */
function initialsOf(name: string): string {
  const parts = (name || "").trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/** Profil éditorial simplifié pour le Mode Pilote (Mon profil). */
export function PilotProfilePane({
  onRequireAuth,
  userEmail,
  onSignOut,
  strategy = null,
  followSuggestions = [],
  followLoading = false,
  followError = "",
  followedHandles = [],
  followCapReached = false,
  onFollowPanelOpen,
  onFollowProfile,
}: PilotProfilePaneProps) {
  const [loading, setLoading] = useState(true);
  const [profile, setProfile] = useState<ProfileDraft | null>(null);
  const [error, setError] = useState("");

  // Chargement paresseux des suggestions : à l'ouverture de CET onglet, pas
  // avant. Le shell dédoublonne (une seule requête par session).
  useEffect(() => {
    void onFollowPanelOpen?.();
  }, [onFollowPanelOpen]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError("");
      try {
        const headers = await authHeaders();
        if (!headers.Authorization) {
          onRequireAuth?.();
          return;
        }
        const res = await fetch(`${DIRECT_API_URL}/me/profile`, { headers });
        if (res.status === 401) {
          onRequireAuth?.();
          return;
        }
        if (!res.ok) throw new Error("Profil indisponible");
        const data = (await res.json()) as ProfileDraft;
        if (!cancelled) setProfile(data);
      } catch (err: unknown) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Erreur de chargement");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [onRequireAuth]);

  if (loading) {
    return (
      <div className="pilot-profile-loading">
        <Loader2 size={28} className="spinning" aria-hidden="true" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="pilot-profile-error" role="alert">
        {error}
      </div>
    );
  }

  const name = profile?.display_name || profile?.brand_name || "—";
  const audience = profile?.target_audience || "Complète ton ICP pour affiner la recherche de prospects.";
  const offer = profile?.core_offer || profile?.business_description || "Décris ton offre pour personnaliser tes posts.";

  return (
    <div className="pilot-profile-pane">
      <header className="pilot-profile-head">
        <h1>Mon profil</h1>
        <p>C’est ce que ton agent utilise pour écrire tes posts et cibler tes prospects.</p>
      </header>
      <dl className="pilot-profile-fields">
        <div>
          <dt>Nom affiché</dt>
          <dd>{name}</dd>
        </div>
        <div>
          <dt>Client idéal (ICP)</dt>
          <dd>{audience}</dd>
        </div>
        <div>
          <dt>Offre</dt>
          <dd>{offer}</dd>
        </div>
      </dl>

      {strategy && (
        <section className="pilot-profile-section" aria-labelledby="pilot-profile-strategy">
          <h2 id="pilot-profile-strategy">
            <Target size={16} strokeWidth={2.2} aria-hidden="true" />
            Ta stratégie
          </h2>
          <ul className="pilot-strategy-list">
            <li>
              <strong>Cible</strong>
              {strategy.target}
            </li>
            <li>
              <strong>Rythme</strong>
              {strategy.frequency}
            </li>
            <li>
              <strong>Structure</strong>
              {strategy.structureHint}
            </li>
          </ul>
        </section>
      )}

      <section className="pilot-profile-section" aria-labelledby="pilot-profile-follow">
        <h2 id="pilot-profile-follow">
          <Users size={16} strokeWidth={2.2} aria-hidden="true" />
          Influenceurs à suivre
        </h2>
        {followLoading && (
          <p className="pilot-profile-note">
            <Loader2 size={14} className="spinning" aria-hidden="true" /> Recherche de profils de ta niche…
          </p>
        )}
        {!followLoading && followError && <p className="pilot-profile-note">{followError}</p>}
        {!followLoading && !followError && followSuggestions.length === 0 && (
          <p className="pilot-profile-note">
            Aucun profil à te proposer pour l’instant — complète ton profil éditorial
            (ton secteur, ta cible, ton offre) et on te suggérera des comptes de ta niche.
          </p>
        )}
        {!followLoading && followSuggestions.length > 0 && (
          <div className="pilot-follow-list">
            {followSuggestions.map((suggestion) => {
              const isFollowed = followedHandles.includes(suggestion.handle);
              return (
                <div key={suggestion.handle} className="pilot-follow-row">
                  <div className="pilot-avatar" aria-hidden="true">
                    {initialsOf(suggestion.name)}
                  </div>
                  <div className="pilot-follow-info">
                    <h3>{suggestion.name}</h3>
                    <p>
                      {suggestion.headline || suggestion.handle}
                      {suggestion.matched_keywords.length > 0
                        ? ` — correspond à ta niche : ${suggestion.matched_keywords.join(" · ")}`
                        : ""}
                    </p>
                  </div>
                  {/* `aria-label` : plusieurs boutons « Suivre » identiques sont
                      indistinguables au lecteur d'écran (et au test). */}
                  <button
                    type="button"
                    className={`pilot-btn pilot-btn-follow${isFollowed ? " done" : ""}`}
                    aria-label={`Suivre ${suggestion.name}`}
                    disabled={isFollowed || (followCapReached && !isFollowed)}
                    title={
                      followCapReached && !isFollowed
                        ? "Tu suis déjà le maximum d’influenceurs. Retires-en un pour en ajouter."
                        : "Surveiller ses nouveaux posts"
                    }
                    onClick={() => onFollowProfile?.(suggestion.handle)}
                  >
                    {isFollowed ? <Check size={14} /> : <UserPlus size={14} />}
                    {isFollowed ? "Suivi" : "Suivre"}
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Compte + déconnexion. ⚠️ Le Mode Pilote n'a pas d'entête d'application :
          sans cette ligne, un client n'a AUCUN moyen de se déconnecter — ni de
          savoir avec quel compte il est. */}
      <section className="pilot-profile-section" aria-labelledby="pilot-profile-account">
        <h2 id="pilot-profile-account">Ton compte</h2>
        <div className="pilot-profile-account">
          <span className="pilot-profile-account-mail">{userEmail || "Connecté"}</span>
          <button type="button" className="pilot-profile-signout" onClick={() => onSignOut?.()}>
            <LogOut size={14} aria-hidden="true" />
            Se déconnecter
          </button>
        </div>
      </section>

      <p className="pilot-profile-foot">
        Pour modifier ton profil ou connecter LinkedIn, passe en premium.
      </p>
    </div>
  );
}

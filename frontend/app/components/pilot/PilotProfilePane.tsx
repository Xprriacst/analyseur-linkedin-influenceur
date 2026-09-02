"use client";

import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { authHeaders } from "../../lib/supabase";

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
};

/** Profil éditorial simplifié pour le Mode Pilote (Mon profil). */
export function PilotProfilePane({ onRequireAuth }: PilotProfilePaneProps) {
  const [loading, setLoading] = useState(true);
  const [profile, setProfile] = useState<ProfileDraft | null>(null);
  const [error, setError] = useState("");

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
      <p className="pilot-profile-foot">
        Pour modifier ton profil ou connecter LinkedIn, passe en{" "}
        <strong>Mode Expert</strong> (aperçu) puis upgrade quand tu es prêt.
      </p>
    </div>
  );
}

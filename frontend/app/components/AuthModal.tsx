"use client";

import { useEffect, useState } from "react";
import { Loader2, X } from "lucide-react";
import { supabase } from "../lib/supabase";

export type AuthMode = "signin" | "signup";

export default function AuthModal({
  open,
  onClose,
  reason,
  defaultMode = "signup",
}: {
  open: boolean;
  onClose: () => void;
  reason?: string;
  defaultMode?: AuthMode;
}) {
  const [mode, setMode] = useState<AuthMode>(defaultMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(false);

  // Reset to the requested mode each time the modal is (re)opened.
  useEffect(() => {
    if (open) {
      setMode(defaultMode);
      setError("");
      setInfo("");
    }
  }, [open, defaultMode]);

  // Close on Escape.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setInfo("");
    setLoading(true);
    try {
      if (mode === "signin") {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
        onClose(); // session set → Home reacts via onAuthStateChange
      } else {
        const { data, error } = await supabase.auth.signUp({
          email,
          password,
          // Flag lu au login pour afficher l'onboarding immédiatement (sans appel backend).
          options: { data: { onboarding_pending: true } },
        });
        if (error) throw error;
        if (data.session) {
          // Email confirmation disabled → instantly logged in.
          onClose();
        } else {
          // Confirmation enabled → no session yet.
          setInfo("Compte créé. Confirme ton e-mail puis connecte-toi pour débloquer ton analyse.");
          setMode("signin");
        }
      }
    } catch (err: any) {
      setError(err.message || "Échec de l'authentification");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-modal-backdrop" onClick={onClose}>
      <form className="auth-modal" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <button type="button" className="auth-modal-close" onClick={onClose} aria-label="Fermer">
          <X size={18} />
        </button>

        <h1 className="auth-title">
          {mode === "signin" ? "Se connecter" : "Crée ton compte gratuit"}
        </h1>
        <p className="auth-sub">
          {reason ||
            (mode === "signin"
              ? "Connecte-toi pour retrouver tes analyses."
              : "Débloque l'analyse complète et conserve ton historique. Sans carte bancaire.")}
        </p>

        <label className="auth-label">Email</label>
        <input
          className="auth-input"
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="toi@exemple.com"
        />

        <label className="auth-label">Mot de passe</label>
        <input
          className="auth-input"
          type="password"
          required
          minLength={6}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="••••••••"
        />

        {error && <div className="error">{error}</div>}
        {info && <div className="auth-info">{info}</div>}

        <button className="auth-submit" type="submit" disabled={loading}>
          {loading ? (
            <Loader2 className="spin" size={16} />
          ) : mode === "signin" ? (
            "Se connecter"
          ) : (
            "Créer mon compte gratuit"
          )}
        </button>

        <button
          type="button"
          className="auth-switch"
          onClick={() => {
            setMode(mode === "signin" ? "signup" : "signin");
            setError("");
            setInfo("");
          }}
        >
          {mode === "signin" ? "Pas de compte ? Créer un compte gratuit" : "Déjà un compte ? Se connecter"}
        </button>
      </form>
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { LogOut, Loader2 } from "lucide-react";
import { supabase } from "../lib/supabase";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setReady(true);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_event, s) => {
      setSession(s);
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  if (!ready) {
    return (
      <div className="auth-shell">
        <Loader2 className="spin" size={28} />
      </div>
    );
  }

  if (!session) {
    return <AuthForm />;
  }

  return (
    <>
      <button
        className="auth-logout"
        title={session.user.email ?? "Déconnexion"}
        onClick={() => supabase.auth.signOut()}
      >
        <LogOut size={16} />
        <span>{session.user.email}</span>
      </button>
      {children}
    </>
  );
}

function AuthForm() {
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setInfo("");
    setLoading(true);
    try {
      if (mode === "signin") {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
      } else {
        const { error } = await supabase.auth.signUp({ email, password });
        if (error) throw error;
        setInfo("Compte créé. Vérifie ta boîte mail si la confirmation est activée, puis connecte-toi.");
        setMode("signin");
      }
    } catch (err: any) {
      setError(err.message || "Échec de l'authentification");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-shell">
      <form className="auth-card" onSubmit={submit}>
        <h1 className="auth-title">LinkedIn Strategy Decoder</h1>
        <p className="auth-sub">
          {mode === "signin" ? "Connecte-toi pour accéder à tes analyses." : "Crée ton compte."}
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
          {loading ? <Loader2 className="spin" size={16} /> : mode === "signin" ? "Se connecter" : "Créer le compte"}
        </button>

        <button
          type="button"
          className="auth-switch"
          onClick={() => { setMode(mode === "signin" ? "signup" : "signin"); setError(""); setInfo(""); }}
        >
          {mode === "signin" ? "Pas de compte ? S'inscrire" : "Déjà un compte ? Se connecter"}
        </button>
      </form>
    </div>
  );
}

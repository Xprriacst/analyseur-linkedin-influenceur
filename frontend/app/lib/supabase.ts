import { createClient } from "@supabase/supabase-js";

// Public values: the anon key is safe to expose in the browser.
const SUPABASE_URL =
  process.env.NEXT_PUBLIC_SUPABASE_URL ?? "https://zcxaxwqkswuefzlzpgvi.supabase.co";
const SUPABASE_ANON_KEY =
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ??
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpjeGF4d3Frc3d1ZWZ6bHpwZ3ZpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODEwMjU2NjIsImV4cCI6MjA5NjYwMTY2Mn0.AO5J-JdO0XYSvaRejq44cvnX1pC6qactw7X9O9-mS9U";

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

/** Returns the current access token (JWT) or null if not signed in. */
export async function getAccessToken(): Promise<string | null> {
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}

/** Authorization header for backend calls, empty object when signed out. */
export async function authHeaders(): Promise<Record<string, string>> {
  const token = await getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

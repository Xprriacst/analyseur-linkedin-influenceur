import { useCallback, useEffect, useState } from "react";
import { supabase } from "../supabase";
import {
  createLead,
  deleteLead,
  listLeads,
  updateLead,
  type LeadInput,
  type LeadStatus,
  type UiLead,
} from "./queries";

export type UseLeadsOptions = {
  status?: LeadStatus;
  monitoredKeywordId?: string;
  sourcePostId?: string;
  limit?: number;
  realtime?: boolean;
};

export function useLeads({
  status,
  monitoredKeywordId,
  sourcePostId,
  limit,
  realtime = true,
}: UseLeadsOptions = {}) {
  const [leads, setLeads] = useState<UiLead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [userId, setUserId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const rows = await listLeads({ status, monitoredKeywordId, sourcePostId, limit });
      setLeads(rows);
    } catch (err: any) {
      setError(err?.message || "Impossible de charger les leads.");
    } finally {
      setLoading(false);
    }
  }, [status, monitoredKeywordId, sourcePostId, limit]);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setUserId(data.session?.user.id ?? null);
    });
    const { data: subscription } = supabase.auth.onAuthStateChange((_event, session) => {
      setUserId(session?.user.id ?? null);
    });
    return () => subscription.subscription.unsubscribe();
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!realtime || !userId) return;

    const channel = supabase
      .channel(`outreach-leads-${userId}`)
      .on(
        "postgres_changes",
        {
          event: "*",
          schema: "public",
          table: "leads",
          filter: `user_id=eq.${userId}`,
        },
        () => {
          void refresh();
        },
      )
      .subscribe();

    return () => {
      void supabase.removeChannel(channel);
    };
  }, [realtime, refresh, userId]);

  const addLead = useCallback(
    async (input: LeadInput) => {
      const lead = await createLead(input);
      setLeads((prev) => [lead, ...prev]);
      return lead;
    },
    [],
  );

  const patchLead = useCallback(async (id: string, patch: Partial<LeadInput>) => {
    const lead = await updateLead(id, patch);
    setLeads((prev) => prev.map((item) => (item.id === id ? lead : item)));
    return lead;
  }, []);

  const removeLead = useCallback(async (id: string) => {
    await deleteLead(id);
    setLeads((prev) => prev.filter((item) => item.id !== id));
  }, []);

  return {
    leads,
    loading,
    error,
    refresh,
    addLead,
    patchLead,
    removeLead,
  };
}

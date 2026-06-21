"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { supabase } from "../supabase";
import { listLeads, toUiLeadFromRealtime } from "./queries";
import type { LeadStatus, UiLead, LeadInput } from "./queries";
import { createLead, updateLead, deleteLead } from "./queries";

export interface UseLeadsOptions {
  status?: LeadStatus;
  monitoredKeywordId?: string;
  sourcePostId?: string;
  limit?: number;
  realtime?: boolean;
}

export function useLeads(options: UseLeadsOptions = {}) {
  const [leads, setLeads] = useState<UiLead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const channelRef = useRef<ReturnType<typeof supabase.channel> | null>(null);

  const { status, monitoredKeywordId, sourcePostId, limit, realtime } = options;

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setUserId(data.session?.user.id ?? null);
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (_event, session) => {
        setUserId(session?.user.id ?? null);
      }
    );

    return () => subscription.unsubscribe();
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listLeads({ status, monitoredKeywordId, sourcePostId, limit });
      setLeads(data);
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setLoading(false);
    }
  }, [status, monitoredKeywordId, sourcePostId, limit]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!realtime || !userId) return;

    const channel = supabase
      .channel(`leads:${userId}`)
      .on(
        "postgres_changes",
        {
          event: "*",
          schema: "public",
          table: "leads",
          filter: `user_id=eq.${userId}`,
        },
        (payload) => {
          if (payload.eventType === "INSERT") {
            setLeads((prev) => [toUiLeadFromRealtime(payload.new), ...prev]);
          } else if (payload.eventType === "UPDATE") {
            setLeads((prev) =>
              prev.map((l) =>
                l.id === payload.new.id ? toUiLeadFromRealtime(payload.new) : l
              )
            );
          } else if (payload.eventType === "DELETE") {
            setLeads((prev) => prev.filter((l) => l.id !== payload.old.id));
          }
        }
      )
      .subscribe();

    channelRef.current = channel;

    return () => {
      supabase.removeChannel(channel);
      channelRef.current = null;
    };
  }, [realtime, userId]);

  const addLead = useCallback(async (input: LeadInput): Promise<UiLead> => {
    const lead = await createLead(input);
    if (!options.realtime) {
      setLeads((prev) => [lead, ...prev]);
    }
    return lead;
  }, [options.realtime]);

  const patchLead = useCallback(
    async (id: string, input: Partial<LeadInput>): Promise<UiLead> => {
      const lead = await updateLead(id, input);
      if (!options.realtime) {
        setLeads((prev) => prev.map((l) => (l.id === id ? lead : l)));
      }
      return lead;
    },
    [options.realtime]
  );

  const removeLead = useCallback(
    async (id: string): Promise<void> => {
      await deleteLead(id);
      if (!options.realtime) {
        setLeads((prev) => prev.filter((l) => l.id !== id));
      }
    },
    [options.realtime]
  );

  return { leads, loading, error, refresh, addLead, patchLead, removeLead };
}

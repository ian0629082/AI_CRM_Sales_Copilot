"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import * as interactionsApi from "@/lib/api/interactions";
import type { InteractionCreate } from "@/lib/api/types";
import { leadKeys } from "@/lib/hooks/use-leads";

export function useCreateInteraction(leadId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: InteractionCreate) =>
      interactionsApi.createInteraction(leadId, payload),
    onSuccess: () => {
      // 新增互動會連帶把 NEW 推進為 CONTACTED，
      // 所以整筆 Lead 都要重抓，不能只更新 Timeline
      queryClient.invalidateQueries({ queryKey: leadKeys.all });
    },
  });
}

export function useDeleteInteraction(leadId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (interactionId: number) =>
      interactionsApi.deleteInteraction(leadId, interactionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: leadKeys.detail(leadId) });
    },
  });
}

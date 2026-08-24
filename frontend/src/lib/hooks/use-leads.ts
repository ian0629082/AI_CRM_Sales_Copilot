"use client";

/**
 * Lead 相關的資料抓取與變更。
 *
 * 把 queryKey 集中在這裡，避免各頁面各自拼字串而導致快取失效失準
 * （例如新增客戶後列表沒更新，往往就是 key 拼錯造成的）。
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import * as leadsApi from "@/lib/api/leads";
import type { LeadCreate, LeadUpdate } from "@/lib/api/types";
import type { LeadListParams } from "@/lib/api/leads";

export const leadKeys = {
  all: ["leads"] as const,
  list: (params: LeadListParams) => [...leadKeys.all, "list", params] as const,
  detail: (id: number) => [...leadKeys.all, "detail", id] as const,
};

export function useLeads(params: LeadListParams = {}) {
  return useQuery({
    queryKey: leadKeys.list(params),
    queryFn: () => leadsApi.listLeads(params),
  });
}

export function useLead(id: number) {
  return useQuery({
    queryKey: leadKeys.detail(id),
    queryFn: () => leadsApi.getLead(id),
    enabled: Number.isFinite(id) && id > 0,
  });
}

export function useCreateLead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: LeadCreate) => leadsApi.createLead(payload),
    onSuccess: () => {
      // 讓所有 lead 列表重新抓取，不管目前套用的是哪組篩選條件
      queryClient.invalidateQueries({ queryKey: leadKeys.all });
    },
  });
}

export function useUpdateLead(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: LeadUpdate) => leadsApi.updateLead(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: leadKeys.all });
    },
  });
}

export function useDeleteLead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => leadsApi.deleteLead(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: leadKeys.all });
    },
  });
}

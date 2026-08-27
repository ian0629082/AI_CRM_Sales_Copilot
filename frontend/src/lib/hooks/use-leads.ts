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
  followUps: () => [...leadKeys.all, "follow-ups"] as const,
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

export function useFollowUps() {
  return useQuery({
    queryKey: leadKeys.followUps(),
    queryFn: () => leadsApi.listFollowUps(),
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

export function useAnalyzeLead(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => leadsApi.analyzeLead(id),
    onSuccess: () => {
      // 解析會改寫 lead 的需求欄位，列表頁的那筆資料也跟著過期了
      queryClient.invalidateQueries({ queryKey: leadKeys.all });
    },
    // 不自動重試：這一次呼叫是有成本的（會真的花錢打 OpenAI）。
    // 要不要再試一次，交給使用者按重試按鈕決定。
    retry: false,
  });
}

/**
 * 請 AI 給一則跟進建議。
 *
 * 刻意**不**讓任何快取失效：這支 API 不會改動客戶的欄位，
 * 讓 lead 重新抓一次只是白跑一趟。
 * 建議本身留在 mutation 的 data 裡就好，畫面直接讀那個。
 */
export function useSuggestFollowUp(id: number) {
  return useMutation({
    mutationFn: () => leadsApi.suggestFollowUp(id),
    // 跟 useAnalyzeLead 同樣不自動重試：每一次呼叫都會真的花錢。
    retry: false,
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

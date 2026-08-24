import { apiRequest } from "@/lib/api/client";
import type {
  Lead,
  LeadCreate,
  LeadDetail,
  LeadListResponse,
  LeadStatus,
  LeadUpdate,
} from "@/lib/api/types";

export type LeadListParams = {
  status?: LeadStatus | null;
  keyword?: string | null;
  skip?: number;
  limit?: number;
};

function buildQuery(params: LeadListParams): string {
  const search = new URLSearchParams();
  // 只帶有值的參數：空字串的 keyword 會讓後端做一次無意義的 LIKE '%%' 查詢
  if (params.status) search.set("status", params.status);
  if (params.keyword) search.set("keyword", params.keyword);
  if (params.skip !== undefined) search.set("skip", String(params.skip));
  if (params.limit !== undefined) search.set("limit", String(params.limit));

  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export function listLeads(params: LeadListParams = {}): Promise<LeadListResponse> {
  return apiRequest<LeadListResponse>(`/leads${buildQuery(params)}`);
}

export function getLead(id: number): Promise<LeadDetail> {
  return apiRequest<LeadDetail>(`/leads/${id}`);
}

export function createLead(payload: LeadCreate): Promise<Lead> {
  return apiRequest<Lead>("/leads", { method: "POST", body: payload });
}

export function updateLead(id: number, payload: LeadUpdate): Promise<Lead> {
  return apiRequest<Lead>(`/leads/${id}`, { method: "PATCH", body: payload });
}

export function deleteLead(id: number): Promise<void> {
  return apiRequest<void>(`/leads/${id}`, { method: "DELETE" });
}

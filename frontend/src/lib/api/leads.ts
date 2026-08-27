import { apiRequest } from "@/lib/api/client";
import type {
  FollowUpResponse,
  Lead,
  LeadAnalyzeResponse,
  LeadCreate,
  LeadDetail,
  LeadFollowUpResponse,
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

/**
 * 今天該聯絡誰。
 *
 * 回傳兩份分開的清單而不是一份排序好的名單 ——
 * 「還沒有人聯絡過」跟「聯絡過但太久沒動」是兩種不同的業務動作。
 */
export function listFollowUps(): Promise<FollowUpResponse> {
  return apiRequest<FollowUpResponse>("/leads/follow-ups");
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

/**
 * 請 AI 解析這位客戶的原話。
 *
 * 這支 API 會等 OpenAI 回應（約 2～5 秒），呼叫端一定要顯示 loading。
 * 失敗時後端回 503（AI 暫時不可用）或 422（這位客戶還沒填原話），
 * 兩者要分開處理，使用者才知道該重試還是該先去補資料。
 */
export function analyzeLead(id: number): Promise<LeadAnalyzeResponse> {
  return apiRequest<LeadAnalyzeResponse>(`/leads/${id}/analyze`, {
    method: "POST",
  });
}

/**
 * 請 AI 給一則跟進建議：下一步動作、建議話術、建議時機。
 *
 * 跟 analyzeLead 最大的差別是**這支不會改動客戶的任何欄位**，
 * 所以呼叫成功後不需要讓客戶資料的快取失效。
 * 建議是給業務看的參考，不是關於這位客戶的新事實。
 */
export function suggestFollowUp(id: number): Promise<LeadFollowUpResponse> {
  return apiRequest<LeadFollowUpResponse>(`/leads/${id}/follow-up-suggestion`, {
    method: "POST",
  });
}

export function deleteLead(id: number): Promise<void> {
  return apiRequest<void>(`/leads/${id}`, { method: "DELETE" });
}

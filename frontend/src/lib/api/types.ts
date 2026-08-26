/**
 * 從後端 OpenAPI 生成的型別中，取出常用的幾個並給它們好記的名字。
 *
 * 不要手寫這些型別 —— 它們的來源是 src/types/api.ts，
 * 由 npm run gen:api 依後端的 OpenAPI schema 自動產生。
 * 後端改欄位，這裡就會編譯失敗，這正是我們要的效果。
 */

import type { components } from "@/types/api";

type Schemas = components["schemas"];

export type Lead = Schemas["LeadRead"];
export type LeadDetail = Schemas["LeadDetail"];
export type LeadCreate = Schemas["LeadCreate"];
export type LeadUpdate = Schemas["LeadUpdate"];
export type LeadListResponse = Schemas["LeadListResponse"];

export type AIAnalysis = Schemas["AIAnalysisRead"];
export type ScoreReason = Schemas["ScoreReasonRead"];
export type FollowUpItem = Schemas["FollowUpItem"];
export type FollowUpResponse = Schemas["FollowUpResponse"];
export type LeadAnalyzeResponse = Schemas["LeadAnalyzeResponse"];

export type Interaction = Schemas["InteractionRead"];
export type InteractionCreate = Schemas["InteractionCreate"];

export type User = Schemas["UserRead"];
export type Token = Schemas["Token"];

export type LeadStatus = Schemas["LeadStatus"];
export type LeadLevel = Schemas["LeadLevel"];
export type LeadSource = Schemas["LeadSource"];
export type InteractionType = Schemas["InteractionType"];
export type Purpose = Schemas["Purpose"];
export type PropertyType = Schemas["PropertyType"];
export type Urgency = Schemas["Urgency"];

"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api/client";
import type { InteractionType, LeadDetail, LeadStatus } from "@/lib/api/types";
import { useCreateInteraction } from "@/lib/hooks/use-interactions";
import {
  useAnalyzeLead,
  useDeleteLead,
  useLead,
  useUpdateLead,
} from "@/lib/hooks/use-leads";
import {
  INTERACTION_TYPE_LABEL,
  LEAD_LEVEL_LABEL,
  LEAD_SOURCE_LABEL,
  LEAD_STATUS_CLASS,
  LEAD_STATUS_LABEL,
  LEAD_STATUS_ORDER,
  PROPERTY_TYPE_LABEL,
  PURPOSE_LABEL,
  formatBudgetRange,
  formatDateTime,
} from "@/lib/lead-display";

const INTERACTION_TYPES: InteractionType[] = [
  "CALL",
  "LINE",
  "EMAIL",
  "MEETING",
  "VIEWING",
  "NOTE",
];

/** 需求欄位裡，哪些是可以由 AI 解析填入的。 */
type RequirementField =
  | "location"
  | "budget_min"
  | "budget_max"
  | "rooms"
  | "property_type"
  | "building_age_max"
  | "parking"
  | "purpose"
  | "purchase_timeline";

/**
 * 判斷這個欄位目前的值是不是 AI 填的。
 *
 * 做法是拿 lead 上的現值跟最近一次解析結果比對，而不是存一個「這欄是 AI 填的」旗標。
 * 好處是業務手動改過之後，徽章會自動消失 —— 值已經不是 AI 給的了，
 * 再掛著「AI 解析」就是在騙人。
 */
function isAiFilled(lead: LeadDetail, field: RequirementField): boolean {
  const parsed = lead.latest_analysis?.parsed_result;
  if (!parsed) return false;

  const aiValue = parsed[field];
  return aiValue !== null && aiValue !== undefined && aiValue === lead[field];
}

/** 顯示單一欄位。值為空時統一顯示破折號，避免畫面出現空白洞。 */
function Field({
  label,
  value,
  aiFilled = false,
}: {
  label: string;
  value: React.ReactNode;
  aiFilled?: boolean;
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1.5">
        <p className="text-xs text-muted-foreground">{label}</p>
        {aiFilled ? (
          <span
            title="這個值由 AI 從客戶原話解析而來，可以手動修改"
            className="rounded bg-violet-100 px-1 py-px text-[10px] leading-4 font-medium text-violet-700 dark:bg-violet-950 dark:text-violet-200"
          >
            AI
          </span>
        ) : null}
      </div>
      <p className="text-sm">{value || "—"}</p>
    </div>
  );
}

export default function LeadDetailPage() {
  // Next 16 起 page 的 params 是 Promise，但 Client Component 用
  // useParams() 仍是同步的，不需要 use() 解包。
  const params = useParams<{ id: string }>();
  const leadId = Number(params.id);
  const router = useRouter();

  const { data: lead, isLoading, isError, error } = useLead(leadId);
  const updateLead = useUpdateLead(leadId);
  const deleteLead = useDeleteLead();
  const createInteraction = useCreateInteraction(leadId);
  const analyzeLead = useAnalyzeLead(leadId);

  const [interactionType, setInteractionType] = useState<InteractionType>("CALL");
  const [interactionContent, setInteractionContent] = useState("");

  async function handleStatusChange(next: string | null) {
    if (!next) return;
    try {
      await updateLead.mutateAsync({ status: next as LeadStatus });
      toast.success("狀態已更新");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "更新失敗");
    }
  }

  async function handleAddInteraction(e: React.FormEvent) {
    e.preventDefault();
    if (!interactionContent.trim()) return;

    try {
      await createInteraction.mutateAsync({
        type: interactionType,
        content: interactionContent.trim(),
      });
      setInteractionContent("");
      toast.success("已新增互動紀錄");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "新增失敗");
    }
  }

  async function handleAnalyze() {
    try {
      await analyzeLead.mutateAsync();
      toast.success("AI 解析完成，需求欄位已更新");
    } catch {
      // 錯誤已經由 mutation 的 isError 狀態接手，在卡片裡就地顯示並附上重試按鈕。
      // 這裡只是避免 unhandled rejection。
    }
  }

  async function handleDelete() {
    if (!window.confirm(`確定要刪除客戶「${lead?.name}」嗎？此操作無法復原。`)) {
      return;
    }
    try {
      await deleteLead.mutateAsync(leadId);
      toast.success("客戶已刪除");
      router.push("/leads");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "刪除失敗");
    }
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (isError || !lead) {
    const is404 = error instanceof ApiError && error.status === 404;
    return (
      <div className="space-y-4">
        <div className="rounded-md border bg-background p-8 text-center">
          <p className="text-muted-foreground">
            {is404 ? "找不到這位客戶" : "載入失敗，請稍後再試"}
          </p>
          <Button className="mt-4" variant="outline" render={<Link href="/leads" />}>
            回客戶列表
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <Link
            href="/leads"
            className="text-sm text-muted-foreground hover:underline"
          >
            ← 客戶列表
          </Link>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold">{lead.name}</h1>
            <Badge variant="secondary" className={LEAD_STATUS_CLASS[lead.status]}>
              {LEAD_STATUS_LABEL[lead.status]}
            </Badge>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Select
            value={lead.status}
            onValueChange={handleStatusChange}
            disabled={updateLead.isPending}
          >
            <SelectTrigger className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {LEAD_STATUS_ORDER.map((s) => (
                <SelectItem key={s} value={s}>
                  {LEAD_STATUS_LABEL[s]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={deleteLead.isPending}
          >
            刪除
          </Button>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">客戶資訊</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              <Field label="電話" value={lead.phone} />
              <Field label="Email" value={lead.email} />
              <Field label="來源" value={LEAD_SOURCE_LABEL[lead.source]} />
              <Field
                label="區域"
                value={lead.location}
                aiFilled={isAiFilled(lead, "location")}
              />
              <Field
                label="預算"
                value={formatBudgetRange(
                  lead.budget_min,
                  lead.budget_max,
                  lead.budget_is_approximate,
                )}
                aiFilled={isAiFilled(lead, "budget_max")}
              />
              <Field
                label="房型"
                value={lead.rooms ? `${lead.rooms} 房` : null}
                aiFilled={isAiFilled(lead, "rooms")}
              />
              <Field
                label="房屋類型"
                value={
                  lead.property_type ? PROPERTY_TYPE_LABEL[lead.property_type] : null
                }
                aiFilled={isAiFilled(lead, "property_type")}
              />
              <Field
                label="屋齡上限"
                value={
                  lead.building_age_max ? `${lead.building_age_max} 年內` : null
                }
                aiFilled={isAiFilled(lead, "building_age_max")}
              />
              <Field
                label="車位"
                value={
                  lead.parking === null || lead.parking === undefined
                    ? null
                    : lead.parking
                      ? "需要"
                      : "不需要"
                }
                aiFilled={isAiFilled(lead, "parking")}
              />
              <Field
                label="購屋目的"
                value={lead.purpose ? PURPOSE_LABEL[lead.purpose] : null}
                aiFilled={isAiFilled(lead, "purpose")}
              />
              <Field
                label="預計時程"
                value={
                  lead.purchase_timeline ? `${lead.purchase_timeline} 個月內` : null
                }
                aiFilled={isAiFilled(lead, "purchase_timeline")}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between gap-2">
              <CardTitle className="text-base">客戶需求（原話）</CardTitle>
              <Button
                size="sm"
                variant="outline"
                onClick={handleAnalyze}
                // 沒有原話就不給按：與其讓使用者按了才看到錯誤訊息，
                // 不如一開始就讓按鈕呈現不可用
                disabled={analyzeLead.isPending || !lead.raw_requirement}
              >
                {analyzeLead.isPending ? "AI 解析中..." : "AI 解析"}
              </Button>
            </CardHeader>
            <CardContent className="space-y-3">
              {lead.raw_requirement ? (
                <p className="text-sm whitespace-pre-wrap">{lead.raw_requirement}</p>
              ) : (
                <p className="text-sm text-muted-foreground">
                  尚未記錄客戶需求。先把客戶說的話記下來，才能交給 AI 解析。
                </p>
              )}

              {analyzeLead.isPending ? (
                <p className="text-xs text-muted-foreground">
                  正在解析，大約需要 2～5 秒⋯⋯
                </p>
              ) : null}

              {/* 失敗時就地顯示，而不是只跳一個會自己消失的 toast ——
                  使用者要能在原地按下重試 */}
              {analyzeLead.isError ? (
                <div className="flex flex-wrap items-center gap-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-900 dark:bg-amber-950/40">
                  <span className="text-amber-900 dark:text-amber-200">
                    {analyzeLead.error instanceof ApiError
                      ? analyzeLead.error.message
                      : "AI 分析目前無法完成"}
                  </span>
                  <Button size="sm" variant="outline" onClick={handleAnalyze}>
                    重試
                  </Button>
                </div>
              ) : null}

              <p className="text-xs text-muted-foreground">
                解析結果會直接填入上方的需求欄位並標示
                <span className="mx-1 rounded bg-violet-100 px-1 py-px text-[10px] font-medium text-violet-700 dark:bg-violet-950 dark:text-violet-200">
                  AI
                </span>
                徽章，隨時可以手動修改。AI 不會清空你已經填好的欄位。
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                互動紀錄
                <span className="ml-2 text-sm font-normal text-muted-foreground">
                  {lead.interactions.length} 筆
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <form onSubmit={handleAddInteraction} className="space-y-2">
                <div className="flex gap-2">
                  <Select
                    value={interactionType}
                    onValueChange={(v) =>
                      setInteractionType((v as InteractionType) ?? "NOTE")
                    }
                  >
                    <SelectTrigger className="w-28">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {INTERACTION_TYPES.map((t) => (
                        <SelectItem key={t} value={t}>
                          {INTERACTION_TYPE_LABEL[t]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Textarea
                    rows={2}
                    placeholder="記錄這次與客戶的互動內容"
                    value={interactionContent}
                    onChange={(e) => setInteractionContent(e.target.value)}
                    className="flex-1"
                  />
                </div>
                <Button
                  type="submit"
                  size="sm"
                  disabled={
                    createInteraction.isPending || !interactionContent.trim()
                  }
                >
                  {createInteraction.isPending ? "新增中..." : "新增紀錄"}
                </Button>
              </form>

              <Separator />

              {lead.interactions.length === 0 ? (
                <p className="py-6 text-center text-sm text-muted-foreground">
                  還沒有互動紀錄
                </p>
              ) : (
                <ol className="space-y-4">
                  {lead.interactions.map((item) => (
                    <li key={item.id} className="flex gap-3">
                      <div className="flex flex-col items-center">
                        <span className="mt-1.5 size-2 rounded-full bg-primary" />
                        <span className="w-px flex-1 bg-border" />
                      </div>
                      <div className="flex-1 space-y-1 pb-2">
                        <div className="flex items-center gap-2">
                          <Badge variant="outline">
                            {INTERACTION_TYPE_LABEL[item.type]}
                          </Badge>
                          <span className="text-xs text-muted-foreground">
                            {formatDateTime(item.created_at)}
                          </span>
                        </div>
                        <p className="text-sm whitespace-pre-wrap">{item.content}</p>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Lead Score</CardTitle>
            </CardHeader>
            <CardContent>
              {lead.lead_score === null || lead.lead_score === undefined ? (
                <div className="space-y-2">
                  <p className="text-3xl font-semibold text-muted-foreground">—</p>
                  <p className="text-xs text-muted-foreground">
                    Sprint 5 加入 Rule-based Scoring Engine 後，
                    這裡會顯示客戶的優先程度與評分理由。
                  </p>
                </div>
              ) : (
                <div className="space-y-2">
                  <p className="text-3xl font-semibold tabular-nums">
                    {lead.lead_score}
                  </p>
                  {lead.lead_level ? (
                    <Badge variant="secondary">
                      {LEAD_LEVEL_LABEL[lead.lead_level]}
                    </Badge>
                  ) : null}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">AI 分析</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {lead.latest_analysis ? (
                <>
                  <Field
                    label="最後解析"
                    value={formatDateTime(lead.latest_analysis.created_at)}
                  />
                  {/* 把型號與 prompt 版本攤在畫面上，是為了讓「這個結果是誰產生的」
                      隨時查得到 —— Sprint 4 比較不同模型的準確率時要靠它 */}
                  <Field label="模型" value={lead.latest_analysis.model} />
                  <Field
                    label="Prompt 版本"
                    value={lead.latest_analysis.prompt_version}
                  />
                  <Field
                    label="耗時"
                    value={
                      lead.latest_analysis.latency_ms
                        ? `${(lead.latest_analysis.latency_ms / 1000).toFixed(1)} 秒`
                        : null
                    }
                  />
                  <Field
                    label="Token"
                    value={
                      lead.latest_analysis.prompt_tokens === null
                        ? null
                        : `${lead.latest_analysis.prompt_tokens} + ${lead.latest_analysis.completion_tokens}`
                    }
                  />
                </>
              ) : (
                <p className="text-xs text-muted-foreground">
                  尚未進行 AI 解析。在「客戶需求（原話）」卡片按下「AI 解析」，
                  就會把客戶說的話整理成結構化欄位。
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">時間</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <Field label="建立時間" value={formatDateTime(lead.created_at)} />
              <Field label="最後更新" value={formatDateTime(lead.updated_at)} />
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

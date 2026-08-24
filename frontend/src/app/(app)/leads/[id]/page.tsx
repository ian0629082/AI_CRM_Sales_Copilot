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
import type { InteractionType, LeadStatus } from "@/lib/api/types";
import { useCreateInteraction } from "@/lib/hooks/use-interactions";
import { useDeleteLead, useLead, useUpdateLead } from "@/lib/hooks/use-leads";
import {
  INTERACTION_TYPE_LABEL,
  LEAD_LEVEL_LABEL,
  LEAD_SOURCE_LABEL,
  LEAD_STATUS_CLASS,
  LEAD_STATUS_LABEL,
  LEAD_STATUS_ORDER,
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

/** 顯示單一欄位。值為空時統一顯示破折號，避免畫面出現空白洞。 */
function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <p className="text-xs text-muted-foreground">{label}</p>
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
              <Field label="區域" value={lead.location} />
              <Field
                label="預算"
                value={formatBudgetRange(lead.budget_min, lead.budget_max)}
              />
              <Field label="房型" value={lead.rooms ? `${lead.rooms} 房` : null} />
              <Field
                label="車位"
                value={
                  lead.parking === null || lead.parking === undefined
                    ? null
                    : lead.parking
                      ? "需要"
                      : "不需要"
                }
              />
              <Field
                label="購屋目的"
                value={lead.purpose ? PURPOSE_LABEL[lead.purpose] : null}
              />
              <Field
                label="預計時程"
                value={
                  lead.purchase_timeline ? `${lead.purchase_timeline} 個月內` : null
                }
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">客戶需求（原話）</CardTitle>
            </CardHeader>
            <CardContent>
              {lead.raw_requirement ? (
                <p className="text-sm whitespace-pre-wrap">{lead.raw_requirement}</p>
              ) : (
                <p className="text-sm text-muted-foreground">尚未記錄客戶需求</p>
              )}
              {/* Sprint 3 會在這裡加上「AI 解析」按鈕，把上面這段話轉成結構化欄位 */}
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
            <CardContent>
              <p className="text-xs text-muted-foreground">
                Sprint 3 會在這裡顯示 AI 從客戶原話解析出的結構化需求，
                Sprint 5 則加上 Follow-up 建議。
              </p>
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

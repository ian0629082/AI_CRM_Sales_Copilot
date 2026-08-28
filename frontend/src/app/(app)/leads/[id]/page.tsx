"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { EditLeadDialog } from "@/components/leads/edit-lead-dialog";
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
  useSuggestFollowUp,
  useUpdateLead,
} from "@/lib/hooks/use-leads";
import {
  INTERACTION_TYPE_LABEL,
  LEAD_LEVEL_CLASS,
  LEAD_LEVEL_LABEL,
  LEAD_SOURCE_LABEL,
  LEAD_STATUS_CLASS,
  LEAD_STATUS_LABEL,
  LEAD_STATUS_ORDER,
  PROPERTY_TYPE_LABEL,
  PURPOSE_LABEL,
  URGENCY_CLASS,
  URGENCY_LABEL,
  formatBudgetRange,
  formatDate,
  formatDateTime,
} from "@/lib/lead-display";

/**
 * 「下次提醒」的快捷選項。
 *
 * 給按鈕而不是日期選擇器，是因為業務記錄互動時想的是「三天後再打給他」，
 * 不是「10 月 29 日」。多一次心算就多一個不填的理由，
 * 而這個欄位不填的代價是客戶會安靜地消失。
 *
 * null 代表「用系統預設」（依互動類型決定），不是「不提醒」。
 */
const FOLLOW_UP_CHOICES: { label: string; days: number | null; mute?: boolean }[] = [
  { label: "預設", days: null },
  { label: "明天", days: 1 },
  { label: "3 天", days: 3 },
  { label: "1 週", days: 7 },
  { label: "2 週", days: 14 },
  { label: "不用提醒", days: null, mute: true },
];

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
  | "purchase_timeline"
  | "urgency";

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

/**
 * 這個時間點是不是已經過了。
 *
 * 跟 isOverdue 不同，這裡要比到「幾點」而不是只比日期：
 * 今天下午三點的帶看，在今天早上十點看還沒發生 ——
 * 只比日期的話，業務一早打開頁面就會看到那場約被標成「上次帶看」。
 */
function hasPassed(isoDateTime: string): boolean {
  return new Date(isoDateTime).getTime() < Date.now();
}

/** 提醒日是不是已經到了或過了。後端用同一條判斷決定要不要進待跟進清單。 */
function isOverdue(isoDate: string): boolean {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return new Date(isoDate) <= today;
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
  const suggestFollowUp = useSuggestFollowUp(leadId);

  const [editOpen, setEditOpen] = useState(false);
  const [interactionType, setInteractionType] = useState<InteractionType>("CALL");
  const [interactionContent, setInteractionContent] = useState("");
  const [followUpChoice, setFollowUpChoice] = useState(0);
  // 這次通話有沒有談定帶看時間。空字串代表沒談到，不會動到原本約好的時間。
  const [viewingAt, setViewingAt] = useState("");

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
      const choice = FOLLOW_UP_CHOICES[followUpChoice];
      await createInteraction.mutateAsync({
        type: interactionType,
        content: interactionContent.trim(),
        next_follow_up_days: choice.days,
        mute_follow_up: choice.mute ?? null,
        // datetime-local 給的是沒有時區的字串，交給瀏覽器換成當地時間的 ISO
        viewing_scheduled_at: viewingAt ? new Date(viewingAt).toISOString() : null,
      });
      setInteractionContent("");
      setFollowUpChoice(0);
      setViewingAt("");
      toast.success(
        viewingAt
          ? "已新增紀錄，帶看前一天會提醒你確認"
          : choice.mute
            ? "已新增紀錄，並關閉這位客戶的提醒"
            : "已新增互動紀錄",
      );
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "新增失敗");
    }
  }

  async function handleAnalyze() {
    try {
      const result = await analyzeLead.mutateAsync();
      // 原話沒變的話後端不會重新呼叫模型，直接沿用上次的結果。
      // 這件事一定要講出來：否則業務按了按鈕、畫面毫無變化，
      // 他會以為壞掉而一直按，而每一次「以為壞掉」都是信任在流失。
      toast.success(
        result.reused
          ? "客戶原話沒有變更，沿用上一次的解析結果（沒有再花一次費用）"
          : "AI 解析完成，需求欄位已更新",
      );
    } catch {
      // 錯誤已經由 mutation 的 isError 狀態接手，在卡片裡就地顯示並附上重試按鈕。
      // 這裡只是避免 unhandled rejection。
    }
  }

  async function handleCancelViewing() {
    // 同一顆按鈕，在「還沒帶看」與「已經帶看完」兩種狀態下做的是不同的事：
    // 前者是取消一個約（有後果），後者只是清掉一筆過期的紀錄。
    // 用同一句話問，其中一種一定會讓人困惑。
    const passed =
      lead?.viewing_scheduled_at != null && hasPassed(lead.viewing_scheduled_at);
    const message = passed
      ? "清除這筆帶看紀錄嗎？"
      : "取消這筆帶看約嗎？帶看前一天就不會再提醒你確認。";

    if (!window.confirm(message)) {
      return;
    }
    try {
      await updateLead.mutateAsync({ viewing_scheduled_at: null });
      toast.success(passed ? "已清除" : "已取消帶看約");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "操作失敗");
    }
  }

  async function handleSuggestFollowUp() {
    try {
      await suggestFollowUp.mutateAsync();
    } catch {
      // 跟 AI 解析一樣，錯誤就地顯示在卡片裡並附重試按鈕
    }
  }

  async function handleCopyTalkingPoint(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast.success("話術已複製");
    } catch {
      // 瀏覽器可能因為權限或非 HTTPS 而擋下剪貼簿。
      // 話術本來就顯示在畫面上，選取複製一樣做得到，不必當成錯誤處理。
      toast.error("無法自動複製，請手動選取文字");
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
          <Button
            className="mt-4"
            variant="outline"
            nativeButton={false}
            render={<Link href="/leads" />}
          >
            回客戶列表
          </Button>
        </div>
      </div>
    );
  }

  // 剛產生的那一則優先；沒有的話顯示上次存下來的，
  // 這樣重新整理頁面後建議還在，不必再花一次錢重產。
  const advice = suggestFollowUp.data?.suggestion ?? lead.latest_follow_up;
  // 既沒有原話也沒有互動紀錄時，模型只能靠猜，後端會直接回 422。
  // 與其讓使用者按了才看到錯誤，不如一開始就把按鈕關掉。
  const canSuggest = Boolean(lead.raw_requirement) || lead.interactions.length > 0;

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
              {/* SelectValue 預設印出原始的 enum 值（NEW、CONTACTED），
                  這裡自己渲染中文，跟旁邊的徽章保持一致 */}
              <SelectValue>{() => LEAD_STATUS_LABEL[lead.status]}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {LEAD_STATUS_ORDER.map((s) => (
                <SelectItem key={s} value={s}>
                  {LEAD_STATUS_LABEL[s]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="outline" onClick={() => setEditOpen(true)}>
            編輯
          </Button>
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
              {/* 急迫程度跟預計時程分開顯示：客戶很少講出明確月數，
                  卻常常講「有點急」，那個訊號不能被時程欄位的空白蓋掉 */}
              <Field
                label="急迫程度"
                value={
                  lead.urgency ? (
                    <Badge variant="secondary" className={URGENCY_CLASS[lead.urgency]}>
                      {URGENCY_LABEL[lead.urgency]}
                    </Badge>
                  ) : null
                }
                aiFilled={isAiFilled(lead, "urgency")}
              />
            </CardContent>
          </Card>

          {/* 跟進建議排在需求原話之前。
              業務打開這一頁想知道的第一件事是「所以我現在該做什麼」，
              客戶原話是拿來查證的，不是拿來讀的。 */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between gap-2">
              <CardTitle className="text-base">AI 跟進建議</CardTitle>
              <Button
                size="sm"
                variant="outline"
                onClick={handleSuggestFollowUp}
                disabled={suggestFollowUp.isPending || !canSuggest}
              >
                {suggestFollowUp.isPending
                  ? "產生中..."
                  : advice
                    ? "重新產生"
                    : "產生建議"}
              </Button>
            </CardHeader>
            <CardContent className="space-y-3">
              {suggestFollowUp.isPending ? (
                <p className="text-xs text-muted-foreground">
                  正在讀客戶資料與互動紀錄，大約需要 3～6 秒⋯⋯
                </p>
              ) : null}

              {suggestFollowUp.isError ? (
                <div className="flex flex-wrap items-center gap-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-900 dark:bg-amber-950/40">
                  <span className="text-amber-900 dark:text-amber-200">
                    {suggestFollowUp.error instanceof ApiError
                      ? suggestFollowUp.error.message
                      : "AI 建議目前無法產生"}
                  </span>
                  <Button size="sm" variant="outline" onClick={handleSuggestFollowUp}>
                    重試
                  </Button>
                </div>
              ) : null}

              {advice?.parsed_result ? (
                <div className="space-y-3">
                  <div className="space-y-1">
                    <p className="text-xs text-muted-foreground">下一步動作</p>
                    <p className="text-sm font-medium">
                      {advice.parsed_result.next_action}
                    </p>
                  </div>

                  <div className="space-y-1">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-xs text-muted-foreground">建議話術</p>
                      <button
                        type="button"
                        onClick={() =>
                          handleCopyTalkingPoint(advice.parsed_result!.talking_point)
                        }
                        className="text-xs text-muted-foreground hover:underline"
                      >
                        複製
                      </button>
                    </div>
                    {/* 話術是這個功能真正省下時間的那一段，所以給它自己的底色，
                        而且要能一鍵複製 —— 業務下一個動作就是貼到 LINE 上。 */}
                    <p className="rounded-md bg-muted p-3 text-sm whitespace-pre-wrap">
                      {advice.parsed_result.talking_point}
                    </p>
                  </div>

                  <div className="space-y-1">
                    <p className="text-xs text-muted-foreground">建議時機</p>
                    <p className="text-sm">{advice.parsed_result.suggested_timing}</p>
                  </div>

                  {advice.parsed_result.evidence.length > 0 ? (
                    <div className="space-y-1 border-t pt-3">
                      <p className="text-xs text-muted-foreground">
                        引用依據（逐字取自客戶說過的話）
                      </p>
                      {/* 把出處攤開來給業務看，他才知道這句話術是有根據的，
                          而不是模型自己編的。這一欄同時也是評估用的指標。 */}
                      <ul className="space-y-1">
                        {advice.parsed_result.evidence.map((quote) => (
                          <li
                            key={quote}
                            className="border-l-2 border-muted-foreground/30 pl-2 text-xs text-muted-foreground"
                          >
                            {quote}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}

                  <p className="text-xs text-muted-foreground">
                    產生於 {formatDateTime(advice.created_at)}，當時分數{" "}
                    {advice.score_snapshot ?? "—"} 分。建議不會改動客戶資料，
                    下次提醒時間仍然由你決定。
                  </p>
                </div>
              ) : suggestFollowUp.isPending ? null : (
                <p className="text-xs text-muted-foreground">
                  {canSuggest
                    ? "依這位客戶的需求、分數與互動歷史，產生下一步該怎麼跟。"
                    : "還沒有客戶原話，也還沒有互動紀錄——先記下一筆，AI 才有東西可以依據。"}
                </p>
              )}
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
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-xs text-muted-foreground">下次提醒</span>
                  {FOLLOW_UP_CHOICES.map((choice, index) => (
                    <button
                      key={choice.label}
                      type="button"
                      onClick={() => setFollowUpChoice(index)}
                      className={
                        "rounded-full border px-2.5 py-1 text-xs transition-colors " +
                        (index === followUpChoice
                          ? "border-primary bg-primary text-primary-foreground"
                          : "border-input hover:bg-muted")
                      }
                    >
                      {choice.label}
                    </button>
                  ))}
                </div>

                {/* 帶看時間跟「下次提醒」放在一起，因為它們回答的是同一件事：
                    這通電話講完，接下來什麼時候還要動作。
                    不另開一個頁面設定 —— 多一個地方要點，就多一個忘記填的理由，
                    而這一欄沒填的代價是白跑一趟。 */}
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs text-muted-foreground">已約帶看</span>
                  <input
                    type="datetime-local"
                    value={viewingAt}
                    onChange={(e) => setViewingAt(e.target.value)}
                    className="rounded-md border border-input bg-transparent px-2 py-1 text-xs"
                  />
                  {viewingAt ? (
                    <>
                      <button
                        type="button"
                        onClick={() => setViewingAt("")}
                        className="text-xs text-muted-foreground hover:underline"
                      >
                        清除
                      </button>
                      <span className="text-xs text-muted-foreground">
                        前一天會提醒你跟客戶確認
                      </span>
                    </>
                  ) : (
                    <span className="text-xs text-muted-foreground">
                      這次談定帶看時間才填
                    </span>
                  )}
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
            <CardContent className="space-y-3">
              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-semibold tabular-nums">
                  {lead.lead_score ?? 0}
                </span>
                <span className="text-sm text-muted-foreground">/ 100</span>
                {lead.lead_level ? (
                  <Badge
                    variant="secondary"
                    className={"ml-auto " + LEAD_LEVEL_CLASS[lead.lead_level]}
                  >
                    {LEAD_LEVEL_LABEL[lead.lead_level]}
                  </Badge>
                ) : null}
              </div>

              {/* 逐條列出分數怎麼來的。
                  「可解釋」不是加分項，是這個分數敢拿來排序的前提 ——
                  一個講不出理由的分數，沒有業務會照著它打電話。 */}
              {lead.score_reasons.length > 0 ? (
                <ul className="space-y-1 border-t pt-3">
                  {lead.score_reasons.map((reason) => (
                    <li
                      key={reason.code}
                      className="flex items-center justify-between text-sm"
                    >
                      <span className="text-muted-foreground">{reason.label}</span>
                      <span
                        className={
                          "tabular-nums " +
                          (reason.points < 0 ? "text-rose-600" : "text-foreground")
                        }
                      >
                        {reason.points > 0 ? `+${reason.points}` : reason.points}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="border-t pt-3 text-xs text-muted-foreground">
                  這位客戶還沒有任何可計分的資訊。填入需求或按「AI 解析」後就會有分數。
                </p>
              )}

              <p className="text-xs text-muted-foreground">
                分數只看客戶本身，不看跟進了多少次——這樣新客戶跟老客戶才能直接比較。
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">跟進提醒</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {/* 帶看排在最上面。業務打開這張卡片時，
                  「我明天有沒有跟這個人約」比「什麼時候該打給他」急得多。 */}
              {/* 帶看時間過了之後，這一塊要改口。
                  一場已經發生的帶看還掛著「已約帶看　前一天會提醒你確認」，
                  是在講一件不會發生的事 —— 業務看兩次就不會再信這張卡片。

                  不自動清掉那個時間，是因為它仍然是有用的資訊：
                  「上次帶看是 8/24」正是業務決定下一步時要看的東西。
                  只是它已經從「待辦」變成了「歷史」，講法要跟著改。 */}
              {lead.viewing_scheduled_at ? (
                hasPassed(lead.viewing_scheduled_at) ? (
                  <div className="space-y-1">
                    <p className="text-xs text-muted-foreground">上次帶看</p>
                    <div className="flex items-center gap-3">
                      <p className="text-sm">
                        {formatDateTime(lead.viewing_scheduled_at)}
                      </p>
                      <button
                        type="button"
                        onClick={handleCancelViewing}
                        disabled={updateLead.isPending}
                        className="text-xs text-muted-foreground hover:underline"
                      >
                        清除
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-1 rounded-md border border-sky-300 bg-sky-50 p-3 dark:border-sky-900 dark:bg-sky-950/40">
                    <p className="text-xs text-sky-900 dark:text-sky-200">📅 已約帶看</p>
                    <p className="text-sm font-medium">
                      {formatDateTime(lead.viewing_scheduled_at)}
                    </p>
                    <div className="flex items-center gap-3">
                      <p className="text-xs text-muted-foreground">
                        前一天會出現在待跟進清單，提醒你先確認
                      </p>
                      <button
                        type="button"
                        onClick={handleCancelViewing}
                        disabled={updateLead.isPending}
                        className="text-xs text-muted-foreground hover:underline"
                      >
                        取消
                      </button>
                    </div>
                  </div>
                )
              ) : null}

              {lead.follow_up_muted ? (
                <div className="rounded-md bg-muted p-3 text-sm">
                  <p className="font-medium">🔕 已關閉提醒</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    這位客戶不會出現在待跟進清單裡。新增一筆互動就會自動恢復提醒。
                  </p>
                </div>
              ) : lead.next_follow_up_at ? (
                <div className="space-y-1">
                  <p className="text-xs text-muted-foreground">下次提醒</p>
                  <p
                    className={
                      "text-sm " +
                      (isOverdue(lead.next_follow_up_at)
                        ? "font-medium text-amber-600 dark:text-amber-400"
                        : "")
                    }
                  >
                    {formatDate(lead.next_follow_up_at)}
                    {isOverdue(lead.next_follow_up_at) ? "（已到期）" : null}
                  </p>
                </div>
              ) : lead.interactions.length > 0 ? (
                /* 聯絡過但沒有提醒日 —— 多半是 Sprint 5 之前留下的資料。
                   這時候不能說「還沒有人聯絡過」，下面明明就有互動紀錄。 */
                <p className="text-xs text-muted-foreground">
                  聯絡過，但還沒設定下次提醒。新增一筆互動時順手選一個時間，
                  在那之前他會一直留在待跟進清單裡。
                </p>
              ) : (
                <p className="text-xs text-muted-foreground">
                  還沒有人聯絡過這位客戶。建檔滿一天後會出現在「新進未聯絡」清單。
                </p>
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

      <EditLeadDialog lead={lead} open={editOpen} onOpenChange={setEditOpen} />
    </div>
  );
}

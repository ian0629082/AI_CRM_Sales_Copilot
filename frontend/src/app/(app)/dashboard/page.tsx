"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { FollowUpItem } from "@/lib/api/types";
import { useFollowUps, useLeads } from "@/lib/hooks/use-leads";
import {
  LEAD_LEVEL_CLASS,
  LEAD_LEVEL_LABEL,
  LEAD_STATUS_CLASS,
  LEAD_STATUS_LABEL,
  LEAD_STATUS_ORDER,
} from "@/lib/lead-display";

/** 一個大數字加一句說明。說明講「這個數字要拿來幹嘛」，不是重複標題。 */
function Stat({
  label,
  value,
  hint,
  accent,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  accent?: string;
}) {
  return (
    <Card>
      <CardContent className="space-y-1 p-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className={"text-2xl font-semibold tabular-nums " + (accent ?? "")}>
          {value}
        </p>
        {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      </CardContent>
    </Card>
  );
}

/** 待跟進清單裡的一列。 */
function FollowUpRow({ item }: { item: FollowUpItem }) {
  const { lead } = item;
  return (
    <li>
      <Link
        href={`/leads/${lead.id}`}
        className="flex items-center gap-3 rounded-md px-2 py-2 transition-colors hover:bg-muted"
      >
        <span className="w-10 shrink-0 text-sm font-semibold tabular-nums">
          {lead.lead_score ?? 0}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">{lead.name}</span>
          {/* 理由直接寫在旁邊，業務不必點進去才知道為什麼被提醒 */}
          <span className="block truncate text-xs text-muted-foreground">
            {item.reason}
          </span>
        </span>
        <Badge variant="secondary" className={LEAD_STATUS_CLASS[lead.status]}>
          {LEAD_STATUS_LABEL[lead.status]}
        </Badge>
      </Link>
    </li>
  );
}

function FollowUpList({
  title,
  description,
  items,
  emptyText,
}: {
  title: string;
  description: string;
  items: FollowUpItem[];
  emptyText: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          {title}
          <span className="text-sm font-normal text-muted-foreground">
            {items.length} 位
          </span>
        </CardTitle>
        <p className="text-xs text-muted-foreground">{description}</p>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            {emptyText}
          </p>
        ) : (
          <ol className="-mx-2 space-y-0.5">
            {items.map((item) => (
              <FollowUpRow key={item.lead.id} item={item} />
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  // limit 拉到上限一次撈完：漏斗與各級人數要算的是全部客戶，
  // 分頁只撈前 50 筆的話這些數字就是錯的。
  const { data: leads, isLoading } = useLeads({ limit: 200 });
  const { data: followUps } = useFollowUps();

  if (isLoading || !leads) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-40" />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const items = leads.items;
  const hot = items.filter((l) => l.lead_level === "HOT").length;
  const warm = items.filter((l) => l.lead_level === "WARM").length;

  const won = items.filter((l) => l.status === "WON").length;
  const lost = items.filter((l) => l.status === "LOST").length;
  // 分母只算已經有結果的客戶。把還在跟進中的算進去，
  // 成交率會隨著新客戶進來而下降 —— 那不是業績變差，是算法有問題。
  const closed = won + lost;
  const conversionRate = closed > 0 ? Math.round((won / closed) * 100) : null;

  const needFollowUp =
    (followUps?.viewing_confirm.length ?? 0) +
    (followUps?.new_uncontacted.length ?? 0) +
    (followUps?.due.length ?? 0);

  const funnel = LEAD_STATUS_ORDER.map((status) => ({
    status,
    count: items.filter((l) => l.status === status).length,
  }));
  const funnelMax = Math.max(1, ...funnel.map((f) => f.count));

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">總覽</h1>
        <p className="text-sm text-muted-foreground">今天該做什麼，看這一頁</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="客戶總數" value={leads.total} />
        <Stat
          label="高意願"
          value={hot}
          hint={`中意願 ${warm} 位`}
          accent="text-red-600 dark:text-red-400"
        />
        <Stat
          label="待跟進"
          value={needFollowUp}
          hint={
            followUps
              ? [
                  followUps.viewing_confirm.length > 0
                    ? `帶看確認 ${followUps.viewing_confirm.length}`
                    : null,
                  `新進 ${followUps.new_uncontacted.length}`,
                  `到期 ${followUps.due.length}`,
                ]
                  .filter(Boolean)
                  .join("・")
              : undefined
          }
          accent={needFollowUp > 0 ? "text-amber-600 dark:text-amber-400" : ""}
        />
        <Stat
          label="成交率"
          value={conversionRate === null ? "—" : `${conversionRate}%`}
          hint={
            closed === 0
              ? "還沒有結案的客戶"
              : `${won} 成交 / ${closed} 已結案`
          }
        />
      </div>

      {/* 帶看確認獨立一區，而且排在最上面、佔滿整行。
          它跟下面兩堆的差別是「漏掉的代價」：
          少打一通跟進電話是少一次接觸，漏掉帶看確認是白跑一趟，
          而那個下午本來可以帶另一組客戶。 */}
      {followUps && followUps.viewing_confirm.length > 0 ? (
        <FollowUpList
          title="📅 明天帶看，今天要確認"
          description="先傳個 LINE 或打通電話跟客戶確認。客戶臨時有事沒講，你就白跑一趟。"
          items={followUps.viewing_confirm}
          emptyText=""
        />
      ) : null}

      {/* 兩堆刻意分開顯示。
          「還沒有人聯絡過」跟「聯絡過但太久沒動」對應兩種不同的業務動作：
          一個是搶第一時間，一個是別讓它冷掉。混在一起的話，
          業務打開看到一長串名單，分不出哪些是還沒認識、哪些是快跑掉了。 */}
      <div className="grid gap-4 lg:grid-cols-2">
        <FollowUpList
          title="🆕 新進未聯絡"
          description="客戶留了資料，還沒有人聯絡過他。第一時間回應的成交率差很多。"
          items={followUps?.new_uncontacted ?? []}
          emptyText="沒有遺漏的新客戶"
        />
        <FollowUpList
          title="🔁 到期跟進"
          description="你設定的提醒日到了。拖越久的排越前面。"
          items={followUps?.due ?? []}
          emptyText="今天沒有到期的跟進"
        />
      </div>

      {followUps && followUps.muted_count > 0 ? (
        /* 靜音的客戶只給數字、不列名單。
           它們不是待辦，混進上面的清單會讓整份清單失去可信度；
           但完全不顯示，業務又會納悶「那個客戶怎麼再也沒出現過」。 */
        <p className="text-xs text-muted-foreground">
          🔕 另有 {followUps.muted_count} 位客戶已關閉提醒，不會出現在上面的清單。
          客戶列表上會標示 🔕。
        </p>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">銷售漏斗</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {funnel.map(({ status, count }) => (
            <div key={status} className="flex items-center gap-3">
              <span className="w-16 shrink-0 text-xs text-muted-foreground">
                {LEAD_STATUS_LABEL[status]}
              </span>
              <div className="h-5 flex-1 overflow-hidden rounded bg-muted">
                <div
                  className="h-full rounded bg-primary/70"
                  style={{ width: `${(count / funnelMax) * 100}%` }}
                />
              </div>
              <span className="w-8 shrink-0 text-right text-sm tabular-nums">
                {count}
              </span>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">意願分佈</CardTitle>
        </CardHeader>
        <CardContent className="flex gap-2">
          {(["HOT", "WARM", "COLD"] as const).map((level) => (
            <div key={level} className="flex-1 rounded-md border p-3 text-center">
              <Badge variant="secondary" className={LEAD_LEVEL_CLASS[level]}>
                {LEAD_LEVEL_LABEL[level]}
              </Badge>
              <p className="mt-2 text-xl font-semibold tabular-nums">
                {items.filter((l) => l.lead_level === level).length}
              </p>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

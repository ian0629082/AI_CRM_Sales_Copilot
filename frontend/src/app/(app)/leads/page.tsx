"use client";

import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { LeadStatus } from "@/lib/api/types";
import { useLeads } from "@/lib/hooks/use-leads";
import {
  LEAD_STATUS_CLASS,
  LEAD_STATUS_LABEL,
  LEAD_STATUS_ORDER,
  formatBudgetRange,
  formatDate,
} from "@/lib/lead-display";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";

const ALL_STATUS = "ALL";

export default function LeadsPage() {
  const [keywordInput, setKeywordInput] = useState("");
  const [status, setStatus] = useState<string>(ALL_STATUS);

  // 每打一個字就打一次 API 太浪費，等使用者停下來再送出。
  // 資料庫在新加坡，這個延遲省下的往返成本很實際。
  const keyword = useDebouncedValue(keywordInput, 300);

  const { data, isLoading, isError, error } = useLeads({
    keyword: keyword || null,
    status: status === ALL_STATUS ? null : (status as LeadStatus),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">客戶管理</h1>
          <p className="text-sm text-muted-foreground">
            {data ? `共 ${data.total} 位客戶` : "載入中..."}
          </p>
        </div>
        {/* Base UI 用 render prop 把樣式套到 Link 上，取代 Radix 的 asChild */}
        <Button render={<Link href="/leads/new" />}>新增客戶</Button>
      </div>

      <div className="flex flex-col gap-2 sm:flex-row">
        <Input
          placeholder="搜尋姓名或電話"
          value={keywordInput}
          onChange={(e) => setKeywordInput(e.target.value)}
          className="sm:max-w-xs"
        />
        <Select
          value={status}
          onValueChange={(v) => setStatus(v ?? ALL_STATUS)}
        >
          <SelectTrigger className="sm:w-40">
            <SelectValue placeholder="全部狀態" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_STATUS}>全部狀態</SelectItem>
            {LEAD_STATUS_ORDER.map((s) => (
              <SelectItem key={s} value={s}>
                {LEAD_STATUS_LABEL[s]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {isError ? (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
          載入失敗：{error instanceof Error ? error.message : "未知錯誤"}
        </div>
      ) : null}

      <div className="rounded-md border bg-background">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>姓名</TableHead>
              <TableHead>狀態</TableHead>
              <TableHead>區域</TableHead>
              <TableHead>預算</TableHead>
              <TableHead className="text-center">房型</TableHead>
              <TableHead className="text-right">分數</TableHead>
              <TableHead className="text-right">建立日期</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={7}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              ))
            ) : data && data.items.length > 0 ? (
              data.items.map((lead) => (
                <TableRow key={lead.id} className="cursor-pointer">
                  <TableCell className="font-medium">
                    <Link href={`/leads/${lead.id}`} className="hover:underline">
                      {lead.name}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant="secondary"
                      className={LEAD_STATUS_CLASS[lead.status]}
                    >
                      {LEAD_STATUS_LABEL[lead.status]}
                    </Badge>
                  </TableCell>
                  <TableCell>{lead.location ?? "—"}</TableCell>
                  <TableCell>
                    {formatBudgetRange(lead.budget_min, lead.budget_max)}
                  </TableCell>
                  <TableCell className="text-center">
                    {lead.rooms ? `${lead.rooms} 房` : "—"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {/* Sprint 5 的 Scoring Engine 才會填這個欄位 */}
                    {lead.lead_score ?? "—"}
                  </TableCell>
                  <TableCell className="text-right text-muted-foreground">
                    {formatDate(lead.created_at)}
                  </TableCell>
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={7} className="h-32 text-center text-muted-foreground">
                  {keyword || status !== ALL_STATUS
                    ? "沒有符合條件的客戶"
                    : "還沒有客戶，點右上角新增第一位"}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

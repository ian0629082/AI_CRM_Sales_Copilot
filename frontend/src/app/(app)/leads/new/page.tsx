"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api/client";
import type { LeadCreate, LeadSource } from "@/lib/api/types";
import { useCreateLead } from "@/lib/hooks/use-leads";
import { LEAD_SOURCE_LABEL } from "@/lib/lead-display";

const LEAD_SOURCES: LeadSource[] = [
  "WEB_FORM",
  "PHONE",
  "REFERRAL",
  "WALK_IN",
  "LINE",
  "OTHER",
];

/**
 * 只要求姓名為必填。
 *
 * 業務接到電話時常常只知道對方姓名，若強制填寫更多欄位，
 * 實際使用時只會被填假資料繞過。其餘的區域、預算、房型等欄位
 * 在 Sprint 3 會由 AI 從 raw_requirement 自動解析出來。
 */
const createLeadSchema = z.object({
  name: z.string().min(1, "請輸入客戶姓名").max(100, "姓名過長"),
  phone: z.string().max(50, "電話過長").optional(),
  email: z.string().email("email 格式不正確").optional().or(z.literal("")),
  source: z.enum(["WEB_FORM", "PHONE", "REFERRAL", "WALK_IN", "LINE", "OTHER"]),
  raw_requirement: z.string().optional(),
});

type CreateLeadForm = z.infer<typeof createLeadSchema>;

export default function NewLeadPage() {
  const router = useRouter();
  const createLead = useCreateLead();

  const {
    register,
    handleSubmit,
    control,
    formState: { errors },
  } = useForm<CreateLeadForm>({
    resolver: zodResolver(createLeadSchema),
    defaultValues: { source: "PHONE" },
  });

  async function onSubmit(values: CreateLeadForm) {
    // 空字串要轉成 undefined，否則後端會把空字串當成有效值存進去
    const payload: LeadCreate = {
      name: values.name,
      source: values.source,
      phone: values.phone || undefined,
      email: values.email || undefined,
      raw_requirement: values.raw_requirement || undefined,
    };

    try {
      const lead = await createLead.mutateAsync(payload);
      toast.success(`已建立客戶「${lead.name}」`);
      router.push(`/leads/${lead.id}`);
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.message : "建立失敗，請稍後再試",
      );
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">新增客戶</h1>
        <p className="text-sm text-muted-foreground">只有姓名是必填的</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">客戶資訊</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="name">
                  姓名 <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="name"
                  placeholder="王小明"
                  aria-invalid={Boolean(errors.name)}
                  {...register("name")}
                />
                {errors.name ? (
                  <p className="text-sm text-destructive">{errors.name.message}</p>
                ) : null}
              </div>

              <div className="space-y-2">
                <Label htmlFor="source">來源</Label>
                {/* Select 不是原生 input，無法用 register，要透過 Controller 接上表單 */}
                <Controller
                  name="source"
                  control={control}
                  render={({ field }) => (
                    <Select
                      value={field.value}
                      onValueChange={(v) => field.onChange(v ?? "OTHER")}
                    >
                      <SelectTrigger id="source" className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {LEAD_SOURCES.map((s) => (
                          <SelectItem key={s} value={s}>
                            {LEAD_SOURCE_LABEL[s]}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                />
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="phone">電話</Label>
                <Input
                  id="phone"
                  placeholder="0912345678"
                  aria-invalid={Boolean(errors.phone)}
                  {...register("phone")}
                />
                {errors.phone ? (
                  <p className="text-sm text-destructive">{errors.phone.message}</p>
                ) : null}
              </div>

              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  placeholder="wang@example.com"
                  aria-invalid={Boolean(errors.email)}
                  {...register("email")}
                />
                {errors.email ? (
                  <p className="text-sm text-destructive">{errors.email.message}</p>
                ) : null}
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="raw_requirement">客戶需求（原話）</Label>
              <Textarea
                id="raw_requirement"
                rows={4}
                placeholder="想找西屯三房，預算大概 2000 萬，希望有車位，自住，最好三個月內買。"
                {...register("raw_requirement")}
              />
              <p className="text-xs text-muted-foreground">
                直接貼上客戶的原話即可。Sprint 3 加入 AI
                後，系統會自動從這段文字解析出區域、預算、房型等結構化欄位。
              </p>
            </div>

            <div className="flex gap-2">
              <Button type="submit" disabled={createLead.isPending}>
                {createLead.isPending ? "建立中..." : "建立客戶"}
              </Button>
              <Button
                type="button"
                variant="outline"
                render={<Link href="/leads" />}
              >
                取消
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

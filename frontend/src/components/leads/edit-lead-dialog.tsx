"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import type { LeadDetail, LeadUpdate } from "@/lib/api/types";
import { useUpdateLead } from "@/lib/hooks/use-leads";
import { PROPERTY_TYPE_LABEL, PURPOSE_LABEL, URGENCY_LABEL } from "@/lib/lead-display";

/**
 * 預算用「萬」當單位。
 *
 * 資料庫存的是元（20000000），但沒有房仲會這樣講話 ——
 * 要業務自己數零，數錯一位就是差十倍，而那個錯誤在畫面上長得跟正確的一樣。
 */
const WAN = 10000;

/**
 * 空字串轉成 null 而不是 undefined。
 *
 * 這是 PATCH 語意上的關鍵差別：後端用 exclude_unset 分辨兩者 ——
 * undefined 是「這次不動這個欄位」，null 是「請把它清空」。
 * 業務把預算整個刪掉，要的是後者。
 */
const optionalNumber = z
  .string()
  .optional()
  .transform((value) => {
    const trimmed = (value ?? "").trim();
    if (trimmed === "") return null;
    const parsed = Number(trimmed);
    return Number.isFinite(parsed) ? parsed : Number.NaN;
  })
  .refine((value) => value === null || !Number.isNaN(value), "請輸入數字")
  .refine((value) => value === null || value >= 0, "不能是負數");

const editLeadSchema = z
  .object({
    name: z.string().min(1, "請輸入客戶姓名").max(100, "姓名過長"),
    phone: z.string().max(50, "電話過長").optional(),
    email: z.string().email("email 格式不正確").optional().or(z.literal("")),
    raw_requirement: z.string().optional(),

    location: z.string().max(100, "區域過長").optional(),
    budget_min: optionalNumber,
    budget_max: optionalNumber,
    budget_is_approximate: z.boolean(),
    rooms: optionalNumber.refine((v) => v === null || v <= 20, "房數請填 20 以下"),
    property_type: z.string(),
    building_age_max: optionalNumber.refine(
      (v) => v === null || v <= 100,
      "屋齡請填 100 以下",
    ),
    parking: z.string(),
    purpose: z.string(),
    purchase_timeline: optionalNumber.refine(
      (v) => v === null || v <= 120,
      "時程請填 120 個月以內",
    ),
    urgency: z.string(),
  })
  .refine(
    (values) =>
      values.budget_min === null ||
      values.budget_max === null ||
      values.budget_min <= values.budget_max,
    { message: "預算下限不能大於上限", path: ["budget_min"] },
  )
  .refine(
    (values) => !values.budget_is_approximate || values.budget_max !== null || values.budget_min !== null,
    {
      // 跟後端 ParsedRequirement 同一條規則。前端先擋是為了給出看得懂的訊息，
      // 而不是讓使用者收到一個 422。
      message: "沒有填預算時不能勾「客戶說的是概數」",
      path: ["budget_is_approximate"],
    },
  );

type EditLeadForm = z.input<typeof editLeadSchema>;
type EditLeadValues = z.output<typeof editLeadSchema>;

/** 下拉選單裡代表「沒有值」的選項。空字串在 Select 上不能當 value。 */
const NONE = "__none__";

function toText(value: number | null | undefined, divisor = 1): string {
  if (value === null || value === undefined) return "";
  return String(value / divisor);
}

function fromSelect(value: string): string | null {
  return value === NONE ? null : value;
}

function defaultsFrom(lead: LeadDetail): EditLeadForm {
  return {
    name: lead.name,
    phone: lead.phone ?? "",
    email: lead.email ?? "",
    raw_requirement: lead.raw_requirement ?? "",

    location: lead.location ?? "",
    budget_min: toText(lead.budget_min, WAN),
    budget_max: toText(lead.budget_max, WAN),
    budget_is_approximate: lead.budget_is_approximate,
    rooms: toText(lead.rooms),
    property_type: lead.property_type ?? NONE,
    building_age_max: toText(lead.building_age_max),
    parking: lead.parking === null || lead.parking === undefined ? NONE : String(lead.parking),
    purpose: lead.purpose ?? NONE,
    purchase_timeline: toText(lead.purchase_timeline),
    urgency: lead.urgency ?? NONE,
  };
}

type Props = {
  lead: LeadDetail;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

/**
 * 編輯客戶資料：基本資料、客戶原話、以及 AI 會解析出來的需求欄位。
 *
 * ### 為什麼原話一定要能改
 *
 * 客戶的需求會變。業務把新需求寫進互動紀錄，但那不會回頭改動上方的需求欄位
 * —— AI 解析只讀原話，不讀互動紀錄。少了這個入口，
 * 「客戶預算加到 1800 了」這件事永遠反映不到客戶資料上。
 *
 * ### 為什麼需求欄位也要能改（而不是只讓 AI 填）
 *
 * 驗證集是 99.6% 不是 100%，抽錯是必然會發生的事。
 * 而且 AI 解析的規則是「只填不清空」（回 null 代表客戶沒提到，不覆蓋既有值），
 * 所以「客戶不要車位了」這種**取消掉某個要求**的變更，
 * 光靠重新解析永遠改不掉 —— 一定要有手動的出口。
 */
export function EditLeadDialog({ lead, open, onOpenChange }: Props) {
  const updateLead = useUpdateLead(lead.id);

  const {
    register,
    handleSubmit,
    control,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<EditLeadForm, unknown, EditLeadValues>({
    resolver: zodResolver(editLeadSchema),
    defaultValues: defaultsFrom(lead),
  });

  // 重新打開時要吃到最新的資料：上一次存檔後（或 AI 解析後）lead 已經變了，
  // 表單若還留著舊的預設值，業務會看到自己剛改的東西又變回去。
  useEffect(() => {
    if (open) reset(defaultsFrom(lead));
  }, [open, lead, reset]);

  async function onSubmit(values: EditLeadValues) {
    const payload: LeadUpdate = {
      name: values.name,
      phone: values.phone || null,
      email: values.email || null,
      raw_requirement: values.raw_requirement || null,

      location: values.location || null,
      budget_min: values.budget_min === null ? null : values.budget_min * WAN,
      budget_max: values.budget_max === null ? null : values.budget_max * WAN,
      budget_is_approximate: values.budget_is_approximate,
      rooms: values.rooms,
      property_type: fromSelect(values.property_type) as LeadUpdate["property_type"],
      building_age_max: values.building_age_max,
      parking: values.parking === NONE ? null : values.parking === "true",
      purpose: fromSelect(values.purpose) as LeadUpdate["purpose"],
      purchase_timeline: values.purchase_timeline,
      urgency: fromSelect(values.urgency) as LeadUpdate["urgency"],
    };

    try {
      await updateLead.mutateAsync(payload);
      toast.success("客戶資料已更新");
      onOpenChange(false);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "更新失敗，請稍後再試");
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>編輯客戶</DialogTitle>
          <DialogDescription>
            改完原話之後，可以再按一次「AI 解析」讓需求欄位跟著更新。
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
          <section className="grid gap-3 sm:grid-cols-3">
            <Field label="姓名" error={errors.name?.message}>
              <Input {...register("name")} />
            </Field>
            <Field label="電話" error={errors.phone?.message}>
              <Input {...register("phone")} inputMode="tel" />
            </Field>
            <Field label="Email" error={errors.email?.message}>
              <Input {...register("email")} inputMode="email" />
            </Field>
          </section>

          <Field
            label="客戶原話"
            hint="客戶自己講的那一句話，是 AI 解析與跟進建議唯一的原料。需求變了就改這裡。"
            error={errors.raw_requirement?.message}
          >
            <Textarea rows={4} {...register("raw_requirement")} />
          </Field>

          <section className="space-y-3">
            <p className="text-sm font-medium">需求</p>

            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="區域" error={errors.location?.message}>
                <Input {...register("location")} placeholder="七期" />
              </Field>
              <Field label="房數" error={errors.rooms?.message}>
                <Input {...register("rooms")} inputMode="numeric" placeholder="3" />
              </Field>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="預算下限（萬）" error={errors.budget_min?.message}>
                <Input {...register("budget_min")} inputMode="numeric" placeholder="1500" />
              </Field>
              <Field label="預算上限（萬）" error={errors.budget_max?.message}>
                <Input {...register("budget_max")} inputMode="numeric" placeholder="2000" />
              </Field>
            </div>

            <Field error={errors.budget_is_approximate?.message}>
              <label className="flex items-center gap-2 text-sm">
                <Controller
                  control={control}
                  name="budget_is_approximate"
                  render={({ field }) => (
                    <input
                      type="checkbox"
                      className="size-4"
                      checked={field.value}
                      onChange={(e) => field.onChange(e.target.checked)}
                    />
                  )}
                />
                {/* 這一欄回答的是「客戶說預算時的語氣」，不是一個數字。
                    「2000 萬左右」與「就是 2000 萬」在計分上是不同的客戶。 */}
                客戶說的是概數（「2000 萬左右」）
              </label>
            </Field>

            <div className="grid gap-3 sm:grid-cols-2">
              <SelectField
                control={control}
                name="property_type"
                label="房屋類型"
                options={Object.entries(PROPERTY_TYPE_LABEL)}
              />
              <Field label="屋齡上限（年）" error={errors.building_age_max?.message}>
                <Input {...register("building_age_max")} inputMode="numeric" placeholder="20" />
              </Field>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <SelectField
                control={control}
                name="parking"
                label="車位"
                options={[
                  ["true", "要車位"],
                  ["false", "不需要車位"],
                ]}
              />
              <SelectField
                control={control}
                name="purpose"
                label="購屋目的"
                options={Object.entries(PURPOSE_LABEL)}
              />
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <Field
                label="預計幾個月內購買"
                hint="客戶沒講明確月數就留空，不要自己推算"
                error={errors.purchase_timeline?.message}
              >
                <Input {...register("purchase_timeline")} inputMode="numeric" placeholder="3" />
              </Field>
              <SelectField
                control={control}
                name="urgency"
                label="急迫程度"
                options={Object.entries(URGENCY_LABEL)}
              />
            </div>
          </section>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              取消
            </Button>
            <Button type="submit" disabled={isSubmitting || updateLead.isPending}>
              {updateLead.isPending ? "儲存中..." : "儲存"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  label,
  hint,
  error,
  children,
}: {
  label?: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      {label ? <Label className="text-xs text-muted-foreground">{label}</Label> : null}
      {children}
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
    </div>
  );
}

/**
 * 每個下拉都要有「未指定」這一項。
 *
 * 少了它，業務一旦選錯就再也回不到空值 —— 而「客戶沒有提到」
 * 跟「客戶說要自住」是完全不同的兩件事，前者不該被迫變成後者。
 */
function SelectField({
  control,
  name,
  label,
  options,
}: {
  control: ReturnType<typeof useForm<EditLeadForm, unknown, EditLeadValues>>["control"];
  name: "property_type" | "parking" | "purpose" | "urgency";
  label: string;
  options: [string, string][];
}) {
  return (
    <Field label={label}>
      <Controller
        control={control}
        name={name}
        render={({ field }) => (
          <Select value={field.value} onValueChange={field.onChange}>
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>未指定</SelectItem>
              {options.map(([value, text]) => (
                <SelectItem key={value} value={value}>
                  {text}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      />
    </Field>
  );
}

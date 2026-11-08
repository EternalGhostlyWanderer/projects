import { AlertTriangle, BarChart3 } from "lucide-react";

import type { BusinessInsight } from "@/features/insights/model";

type RiskOpportunityCountsProps = {
  insight: BusinessInsight;
  /* compact — для виджета на главной: меньше, чем на карточке ленты. */
  size?: "large" | "compact";
};

/* Сколько рисков и возможностей нашёл разбор; неразобранное событие — серой меткой. */
export function RiskOpportunityCounts({ insight, size = "large" }: RiskOpportunityCountsProps) {
  const compact = size === "compact";
  if (insight.isPending) {
    return (
      <span
        className={`inline-flex items-center rounded-md bg-[#f0f2f5] font-semibold text-[#5b6677] ${
          compact ? "h-6 px-2 text-[12px]" : "h-7 px-2.5 text-[13px]"
        }`}
      >
        {insight.attentionLabel}
      </span>
    );
  }
  const riskCount = insight.riskCount ?? insight.impact.risks.length;
  const opportunityCount = insight.opportunityCount ?? insight.impact.opportunities.length;
  const chip = compact
    ? "h-6 gap-1.5 rounded-md px-2 text-[12px]"
    : "h-8 gap-2 rounded-lg px-3 text-[15px]";
  const number = compact ? "text-[14px] leading-none" : "text-[18px] leading-none";
  const icon = compact ? "size-3.5" : "size-[18px]";
  return (
    <span className="flex flex-wrap items-center gap-2">
      <span
        className={`inline-flex items-center bg-[#fff0d4] font-semibold text-[#b76800] ${chip}`}
        title="Риски для компании в разборе"
      >
        <AlertTriangle className={`${icon} fill-current`} aria-hidden="true" />
        <span className={number}>{riskCount}</span>
        {plural(riskCount, "риск", "риска", "рисков")}
      </span>
      <span
        className={`inline-flex items-center bg-[#e9f7ed] font-semibold text-[#21864a] ${chip}`}
        title="Возможности для компании в разборе"
      >
        <BarChart3 className={icon} aria-hidden="true" />
        <span className={number}>{opportunityCount}</span>
        {plural(opportunityCount, "возможность", "возможности", "возможностей")}
      </span>
    </span>
  );
}

function plural(count: number, one: string, few: string, many: string): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

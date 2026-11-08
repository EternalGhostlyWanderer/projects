import { ArrowRight, ChevronRight, EyeOff, FileText } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { RiskOpportunityCounts } from "@/components/insights/RiskOpportunityCounts";
import type { BusinessInsight, RelevanceLevel } from "@/features/insights/model";
import { isViewed, markViewed } from "@/features/insights/viewed";

const dateFormatter = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric",
  month: "long",
});

type BusinessInsightCardProps = {
  insight: BusinessInsight;
  /* Скрыть событие из ленты компании (вебинар, вопрос 62); это и сигнал качества ленты. */
  onHide?: () => void;
};

export function BusinessInsightCard({ insight, onHide }: BusinessInsightCardProps) {
  const [isRelevanceOpen, setIsRelevanceOpen] = useState(false);
  const [viewed, setViewed] = useState(() => isViewed(insight.id));
  const sourceCount = Math.max(
    1,
    insight.eventSources?.length ??
      insight.evidence.filter((evidence) => evidence.type === "FACT").length,
  );

  return (
    <article
      className={`group relative rounded-[12px] border px-5 py-3.5 transition hover:-translate-y-0.5 hover:border-[#d9dde2] hover:shadow-[0_9px_24px_rgba(37,51,68,0.07)] ${
        viewed
          ? "border-[#eceef1] bg-[#f6f7f9] opacity-80 shadow-none"
          : "border-[#e5e8eb] bg-white shadow-[0_5px_18px_rgba(37,51,68,0.035)]"
      }`}
    >
      <Link
        to={`/insights/${insight.id}?company=${encodeURIComponent(insight.companyId)}`}
        onClick={() => {
          markViewed(insight.id);
          setViewed(true);
        }}
        aria-label={`Открыть анализ: ${insight.title}`}
        className="absolute inset-0 rounded-[12px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ef3124]/40"
      />

      <div className="relative pointer-events-none">
        <div className="flex items-center justify-between gap-3">
          <RiskOpportunityCounts insight={insight} />
          <span className="flex items-center gap-2">
            {onHide ? (
              <button
                type="button"
                onClick={onHide}
                title="Скрыть: событие не важно для компании"
                aria-label={`Скрыть событие: ${insight.title}`}
                className="pointer-events-auto relative z-10 inline-flex items-center gap-1 rounded-md px-2 py-1 text-[12px] text-[#687386] opacity-70 transition hover:bg-[#f0f2f5] hover:opacity-100"
              >
                <EyeOff className="size-3.5" aria-hidden="true" /> Скрыть
              </button>
            ) : null}
            <ChevronRight className="size-4 text-[#647184] transition group-hover:translate-x-0.5" />
          </span>
        </div>

        <p className="mt-2 text-[12px] font-medium text-[#687386]">
          {insight.category} <span className="px-1.5">·</span>
          {dateFormatter.format(new Date(insight.publishedAt))}
          {insight.originalTitle || insight.untranslated ? (
            <>
              <span className="px-1.5">·</span>
              <span
                title={insight.originalTitle ? `Оригинал: ${insight.originalTitle}` : undefined}
                className="pointer-events-auto relative z-10"
              >
                {insight.originalTitle ? "перевод с английского" : "англ., перевод готовится"}
              </span>
            </>
          ) : null}
          {insight.relevanceScore !== undefined ? (
            <>
              <span className="px-1.5">·</span>
              <button
                type="button"
                aria-expanded={isRelevanceOpen}
                onClick={() => setIsRelevanceOpen((isOpen) => !isOpen)}
                className="pointer-events-auto relative z-10 border-b border-dashed border-[#98a2b3] font-semibold text-[#354052] transition hover:border-[#ef3124] hover:text-[#d92a1e]"
              >
                {relevanceLabel(insight.relevanceLevel)}
              </button>
            </>
          ) : null}
        </p>

        {isRelevanceOpen && insight.relevanceScore !== undefined ? (
          <div className="pointer-events-auto relative z-10 mt-2 max-w-[700px] rounded-lg border border-[#e0e5ea] bg-[#f7f9fb] px-3 py-2.5 text-[12px] text-[#4f5a69]">
            <p className="font-semibold text-[#27313f]">Почему событие попало в ленту</p>
            {insight.relevanceBreakdown?.length ? (
              <ul className="mt-1.5 space-y-1">
                {insight.relevanceBreakdown.map((reason) => (
                  <li key={reason}>• {reason}</li>
                ))}
              </ul>
            ) : (
              <p className="mt-1.5">
                {insight.cardCaveat ?? "Найдены совпадения с профилем компании."}
              </p>
            )}
            <p className="mt-2 text-[11px] text-[#7a8494]">
              Внутренний расчёт релевантности: {insight.relevanceScore}/100. Это не вероятность и не
              оценка качества компании.
            </p>
          </div>
        ) : null}
        <h3
          className={`mt-1 max-w-[680px] text-[20px] leading-[1.08] tracking-[-0.025em] ${
            viewed ? "font-medium text-[#4c596a]" : "font-semibold text-[#111318]"
          }`}
        >
          {insight.title}
          {viewed ? (
            <span className="ml-2 align-middle text-[11px] font-normal text-[#8a94a3]">
              просмотрено
            </span>
          ) : null}
        </h3>
        <p className="mt-1.5 max-w-[700px] text-[14px] leading-5 text-[#3f4857]">
          {insight.cardSummary}
        </p>

        <div className="mt-2.5 flex items-end justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[12px] text-[#687386]">
              <FileText className="size-4 shrink-0 text-[#354052]" aria-hidden="true" />
              <span className="font-medium text-[#354052]">
                {sourceCount} {sourceCount === 1 ? "источник" : "источника"}
              </span>
              <span>·</span>
              <span className="truncate">{insight.provenanceLabel}</span>
            </div>
            {insight.cardCaveat ? (
              <p className="mt-1 text-[11px] text-[#8490a1]">{insight.cardCaveat}</p>
            ) : null}
          </div>
          <span className="inline-flex shrink-0 items-center gap-2 text-[13px] font-semibold text-[#ef3124]">
            {insight.isPending ? "Запустить анализ" : "Подробнее"}
            <ArrowRight className="size-4" aria-hidden="true" />
          </span>
        </div>
      </div>
    </article>
  );
}

function relevanceLabel(level: RelevanceLevel): string {
  if (level === "high") return "Высокая значимость";
  if (level === "medium") return "Средняя значимость";
  return "Косвенное влияние";
}

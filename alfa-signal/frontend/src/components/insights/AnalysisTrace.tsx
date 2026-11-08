import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ListChecks } from "lucide-react";
import { useState } from "react";

import { InlineLoadingState } from "@/components/insights/InsightStates";
import { fetchTrace } from "@/features/insights/dataSource";
import { insightQueryKeys } from "@/features/insights/queries";

const PHASE_LABELS: Record<string, string> = {
  plan: "План",
  tool: "Инструмент",
  synthesize: "Анализ",
  verify: "Проверка",
  revise: "Пересмотр",
  finalize: "Итог",
};

type AnalysisTraceProps = {
  insightId: string;
};

export function AnalysisTrace({ insightId }: AnalysisTraceProps) {
  const [isOpen, setIsOpen] = useState(false);
  const traceQuery = useQuery({
    queryKey: insightQueryKeys.trace(insightId),
    queryFn: () => fetchTrace(insightId),
    enabled: isOpen,
    staleTime: Infinity,
  });

  return (
    <section className="rounded-[12px] border border-[#e3e7eb] bg-white p-5 shadow-[0_4px_18px_rgba(37,51,68,0.025)]">
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        aria-expanded={isOpen}
        className="flex w-full items-center justify-between gap-3 text-left"
      >
        <span className="flex items-center gap-2 text-[18px] font-semibold">
          <ListChecks className="size-5" aria-hidden="true" /> Ход анализа
        </span>
        <ChevronDown
          className={`size-4 transition ${isOpen ? "rotate-180" : ""}`}
          aria-hidden="true"
        />
      </button>

      {isOpen ? (
        <div className="mt-3">
          {traceQuery.isPending ? <InlineLoadingState label="Загружаем шаги агента" /> : null}
          {traceQuery.isError ? (
            <p className="text-[12px] text-[#c6261b]">{traceQuery.error.message}</p>
          ) : null}
          {traceQuery.data ? (
            <>
              <p className="text-[12px] text-[#647184]">
                Вызовов инструментов: {traceQuery.data.toolCalls} · итераций проверки:{" "}
                {traceQuery.data.rounds}
              </p>
              <ol className="mt-3 space-y-2">
                {traceQuery.data.steps.map((step) => (
                  <li key={step.n} className="rounded-md border border-[#dfe4e9] p-2.5">
                    <p className="text-[12px] font-semibold">
                      {step.n}. {PHASE_LABELS[step.phase] ?? step.phase} · {step.name}
                      {step.status !== "ok" ? (
                        <span className="ml-2 rounded bg-[#fff0d4] px-1.5 py-0.5 text-[10px] text-[#b76800]">
                          {step.status}
                        </span>
                      ) : null}
                    </p>
                    {step.reason ? (
                      <p className="mt-1 text-[11px] text-[#7b8492]">Зачем: {step.reason}</p>
                    ) : null}
                    {step.outputSummary ? (
                      <p className="mt-1 text-[11px] leading-4 text-[#4f5a69]">
                        {step.outputSummary}
                      </p>
                    ) : null}
                    {step.error ? (
                      <p className="mt-1 text-[11px] text-[#c6261b]">{step.error}</p>
                    ) : null}
                  </li>
                ))}
              </ol>
            </>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

import { ArrowRight, CheckCircle2 } from "lucide-react";
import { Link } from "react-router";

import type { PriorityAction } from "@/features/insights/model";

type PriorityActionPanelProps = {
  action: PriorityAction | null;
};

export function PriorityActionPanel({ action }: PriorityActionPanelProps) {
  return (
    <section className="rounded-3xl bg-[#171719] p-5 text-white shadow-[0_6px_24px_rgba(19,20,22,0.1)]">
      <p className="text-xs font-semibold uppercase tracking-[0.1em] text-white/65">
        Приоритетное действие
      </p>
      {action ? (
        <>
          <div className="mt-3 flex items-start gap-3">
            <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-[#ef3124]" aria-hidden="true" />
            <h2 className="text-lg font-semibold leading-6">{action.title}</h2>
          </div>
          <p className="mt-3 text-sm leading-6 text-white/75">{action.rationale}</p>
          <Link
            to={`/insights/${action.insightId}`}
            className="mt-4 inline-flex items-center gap-2 rounded-lg text-sm font-semibold text-white transition hover:text-white/75 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/40"
          >
            Открыть связанный анализ
            <ArrowRight className="size-4" aria-hidden="true" />
          </Link>
        </>
      ) : (
        <p className="mt-3 text-sm leading-6 text-white/75">
          Обоснованное приоритетное действие пока не определено. Уточните данные профиля компании.
        </p>
      )}
    </section>
  );
}

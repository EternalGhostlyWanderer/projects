import type { EvidenceType } from "@/features/insights/model";

const evidenceLabels: Record<EvidenceType, string> = {
  FACT: "Факт",
  BANK_ANALYSIS: "Мнение банка",
  AI_INFERENCE: "Ответ ИИ",
  HYPOTHESIS: "Требует проверки",
};

const evidenceHints: Record<EvidenceType, string> = {
  FACT: "Прямо записано в новости или в данных компании; есть ссылка на источник",
  BANK_ANALYSIS: "Тезис из аналитики Альфа-Банка; есть ссылка на документ и страницу",
  AI_INFERENCE:
    "Сформулировал ИИ на основе фактов и аналитики банка или общих знаний; не позиция банка",
  HYPOTHESIS: "Предположение: чтобы на него опираться, нужны дополнительные данные",
};

const evidenceStyles: Record<EvidenceType, string> = {
  FACT: "bg-[#eceef1] text-[#4f5661] ring-black/5",
  BANK_ANALYSIS: "bg-[#eceef1] text-[#4f5661] ring-black/5",
  AI_INFERENCE: "bg-[#e9f7ed] text-[#21864a] ring-[#21864a]/15",
  HYPOTHESIS: "bg-amber-50 text-amber-800 ring-amber-700/15",
};

type EvidenceBadgeProps = {
  type: EvidenceType;
};

export function EvidenceBadge({ type }: EvidenceBadgeProps) {
  return (
    <span
      title={evidenceHints[type]}
      className={`inline-flex shrink-0 whitespace-nowrap rounded-md px-2 py-1 text-[11px] font-semibold ring-1 ${evidenceStyles[type]}`}
    >
      {evidenceLabels[type]}
    </span>
  );
}

/* Расшифровка меток: на чём основано каждое утверждение. */
export function EvidenceLegend() {
  return (
    <details className="rounded-[10px] border border-[#e3e7eb] bg-white px-4 py-2 text-[12px] text-[#4f5968]">
      <summary className="cursor-pointer font-medium text-[#384252]">
        Как читать метки утверждений
      </summary>
      <ul className="mt-2 space-y-1.5 pb-1">
        {(Object.keys(evidenceLabels) as EvidenceType[]).map((type) => (
          <li key={type} className="flex items-start gap-2">
            <EvidenceBadge type={type} />
            <span className="pt-1">{evidenceHints[type]}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}

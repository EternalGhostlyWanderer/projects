import { Landmark, ShieldQuestion } from "lucide-react";

import type { Evidence } from "@/features/insights/model";

type BankAnalysisBlockProps = {
  evidence: Evidence[];
};

export function BankAnalysisBlock({ evidence }: BankAnalysisBlockProps) {
  const bankEvidence = evidence.find((item) => item.type === "BANK_ANALYSIS");
  const isConfirmed = Boolean(
    bankEvidence?.sourceTitle && bankEvidence.sourceDate && bankEvidence.sourcePage,
  );

  return (
    <section
      className={`rounded-2xl border ${
        isConfirmed ? "border-[#ef3124]/20 bg-[#fff8f7]" : "border-black/7 bg-[#f7f7f8]"
      } p-5 sm:p-6`}
      aria-label="Аналитика Альфа-Банка"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span
            className={`grid size-8 place-items-center rounded-xl ${
              isConfirmed ? "bg-[#ef3124] text-white" : "bg-white text-[#56585d]"
            }`}
          >
            {isConfirmed ? (
              <Landmark className="size-4" aria-hidden="true" />
            ) : (
              <ShieldQuestion className="size-4" aria-hidden="true" />
            )}
          </span>
          <h4 className="text-sm font-semibold">Аналитика Альфа-Банка</h4>
        </div>
        <span
          className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${
            isConfirmed ? "bg-[#ef3124]/10 text-[#c6261b]" : "bg-white text-muted-foreground"
          }`}
        >
          {isConfirmed ? "Подтверждено материалом банка" : "Позиция не установлена"}
        </span>
      </div>

      {bankEvidence && isConfirmed ? (
        <>
          <p className="mt-4 text-base leading-6 text-[#303136]">{bankEvidence.text}</p>
          <p className="mt-3 text-xs leading-5 text-muted-foreground">
            {bankEvidence.sourceTitle} · {bankEvidence.sourceDate} · страница{" "}
            {bankEvidence.sourcePage}
          </p>
        </>
      ) : (
        <>
          <p className="mt-3 text-sm leading-6 text-[#4d4e53]">
            Позиция Альфа-Банка по этому событию не установлена: в подключённых материалах нет
            подтверждённого релевантного тезиса.
          </p>
          <p className="mt-3 text-xs leading-5 text-[#696a70]">
            Тезис и реквизиты «документ · дата · страница» появятся только после подключения
            реального материала банка.
          </p>
        </>
      )}
    </section>
  );
}

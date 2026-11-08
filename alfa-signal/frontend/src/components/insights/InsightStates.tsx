import { CircleAlert, Inbox, LoaderCircle, RefreshCw } from "lucide-react";

type InsightErrorStateProps = {
  message: string;
  onRetry: () => void;
};

export function InsightLoadingState() {
  return (
    <div className="space-y-4" role="status" aria-label="Загрузка аналитики">
      {[0, 1].map((item) => (
        <div
          key={item}
          className="animate-pulse rounded-2xl bg-white p-6 ring-1 ring-black/[0.035]"
        >
          <div className="h-3 w-40 rounded bg-black/8" />
          <div className="mt-4 h-6 w-3/4 rounded bg-black/8" />
          <div className="mt-5 h-16 rounded bg-black/5" />
          <div className="mt-4 h-9 w-40 rounded bg-black/8" />
        </div>
      ))}
      <span className="sr-only">Загружаем персональные инсайты</span>
    </div>
  );
}

export function InsightErrorState({ message, onRetry }: InsightErrorStateProps) {
  return (
    <section className="rounded-2xl bg-white p-6 text-center ring-1 ring-black/[0.04]" role="alert">
      <CircleAlert className="mx-auto size-7 text-[#ef3124]" aria-hidden="true" />
      <h2 className="mt-3 text-lg font-semibold">Не удалось загрузить аналитику</h2>
      <p className="mt-2 text-sm text-[#5f6065]">{message}</p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-4 inline-flex h-10 items-center gap-2 rounded-xl bg-[#171719] px-4 text-sm font-medium text-white transition hover:bg-black/80 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-[#ef3124]/20"
      >
        <RefreshCw className="size-4" aria-hidden="true" />
        Повторить
      </button>
    </section>
  );
}

type InsightEmptyStateProps = {
  onReset?: () => void;
};

export function InsightEmptyState({ onReset }: InsightEmptyStateProps) {
  return (
    <section className="rounded-2xl bg-white p-8 text-center ring-1 ring-black/[0.04]">
      <Inbox className="mx-auto size-7 text-[#696a70]" aria-hidden="true" />
      <h2 className="mt-3 text-lg font-semibold">Подходящих событий нет</h2>
      <p className="mt-2 text-sm text-[#5f6065]">
        Для выбранной компании и фильтра релевантные инсайты пока не найдены.
      </p>
      {onReset ? (
        <button
          type="button"
          onClick={onReset}
          className="mt-4 inline-flex h-9 items-center rounded-xl bg-[#f1f2f4] px-3.5 text-sm font-medium transition hover:bg-[#e7e8ea] focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-[#ef3124]/20"
        >
          Сбросить фильтр
        </button>
      ) : null}
    </section>
  );
}

export function InlineLoadingState({
  label,
  inverse = false,
}: {
  label: string;
  inverse?: boolean;
}) {
  return (
    <div
      className={`flex items-center gap-2 text-sm ${inverse ? "text-white/75" : "text-[#5f6065]"}`}
      role="status"
    >
      <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
      {label}
    </div>
  );
}

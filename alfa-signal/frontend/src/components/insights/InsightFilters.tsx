export type InsightFilterValue = "all" | "risk" | "opportunity" | "high";

type InsightFiltersProps = {
  value: InsightFilterValue;
  onChange: (value: InsightFilterValue) => void;
  counts: Record<InsightFilterValue, number>;
};

const filters: Array<{ value: InsightFilterValue; label: string }> = [
  { value: "all", label: "Все события" },
  { value: "risk", label: "Риски" },
  { value: "opportunity", label: "Возможности" },
  { value: "high", label: "Высокая значимость" },
];

export function InsightFilters({ value, onChange, counts }: InsightFiltersProps) {
  return (
    <div className="flex gap-2 overflow-x-auto pb-1" role="group" aria-label="Фильтры инсайтов">
      {filters.map((filter) => {
        const isActive = value === filter.value;

        return (
          <button
            key={filter.value}
            type="button"
            aria-pressed={isActive}
            onClick={() => onChange(filter.value)}
            className={`inline-flex h-9 shrink-0 items-center gap-2 rounded-xl px-3.5 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-[#ef3124]/20 ${
              isActive
                ? "bg-[#171719] text-white shadow-sm"
                : "bg-white text-[#4d4e53] ring-1 ring-black/6 hover:bg-[#f7f7f8] hover:text-foreground"
            }`}
          >
            {filter.label}
            <span
              className={`rounded-md px-1.5 py-0.5 text-[11px] ${
                isActive ? "bg-white/12 text-white/85" : "bg-[#f1f2f4] text-[#696a70]"
              }`}
            >
              {counts[filter.value]}
            </span>
          </button>
        );
      })}
    </div>
  );
}

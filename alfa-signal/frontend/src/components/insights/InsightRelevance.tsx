type InsightRelevanceProps = {
  reasons: string[];
  compact?: boolean;
};

export function InsightRelevance({ reasons, compact = false }: InsightRelevanceProps) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-[0.08em] text-[#65666b]">
        Почему это важно компании
      </p>
      <ul className={`mt-2 flex flex-wrap ${compact ? "gap-1.5" : "gap-2"}`}>
        {reasons.map((reason) => (
          <li
            key={reason}
            className="rounded-lg bg-[#f1f2f4] px-2.5 py-1 text-xs font-medium text-[#46474c]"
          >
            {reason}
          </li>
        ))}
      </ul>
    </div>
  );
}

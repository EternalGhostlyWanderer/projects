import { ArrowRight } from "lucide-react";

type ImpactChainProps = {
  mechanism: string;
  compact?: boolean;
};

export function ImpactChain({ mechanism, compact = false }: ImpactChainProps) {
  const stages = mechanism.split("→").map((stage) => stage.trim());

  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-[0.08em] text-[#65666b]">
        Канал влияния
      </p>
      <ol className={`mt-2 flex flex-wrap items-center ${compact ? "gap-1.5" : "gap-2"}`}>
        {stages.map((stage, index) => (
          <li key={stage} className="contents">
            <span className="text-sm font-medium leading-5 text-[#35363a]">{stage}</span>
            {index < stages.length - 1 ? (
              <ArrowRight className="size-3.5 shrink-0 text-[#8a8b90]" aria-hidden="true" />
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, ExternalLink } from "lucide-react";
import { Link } from "react-router";

import { insightQueryKeys } from "@/features/insights/queries";
import { PENDING_PREFIX } from "@/features/insights/dataSource";
import { fetchDigest } from "@/features/insights/userActions";

/* «Главное за сутки» (если за сутки пусто — за неделю): три самых важных события компании.
   Заголовок ведёт на источник новости, ссылка ниже — на разбор. */
export function DigestPanel({ companyId }: { companyId: string }) {
  const digestQuery = useQuery({
    queryKey: [...insightQueryKeys.all, "digest", companyId],
    queryFn: async () => {
      const day = await fetchDigest(companyId, 24);
      return day.items.length ? day : fetchDigest(companyId, 24 * 7);
    },
    enabled: Boolean(companyId),
  });
  const digest = digestQuery.data;
  if (!digest || !digest.items.length) return null;

  return (
    <section className="rounded-[12px] border border-[#e5e8eb] bg-white p-5 shadow-[0_5px_18px_rgba(37,51,68,0.035)]">
      <h2 className="text-[18px] font-semibold tracking-[-0.02em]">
        Главное за {digest.hours <= 24 ? "сутки" : "неделю"}
      </h2>
      <ol className="mt-3 space-y-3">
        {digest.items.map((item, index) => {
          const insightPath = `/insights/${item.insight ? item.insight.insight_id : `${PENDING_PREFIX}${item.event.event_id}`}?company=${encodeURIComponent(companyId)}`;
          return (
            <li key={item.event.event_id} className="text-[13px] leading-5">
              <a
                href={item.event.url}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-[#1f2733] hover:text-[#ef3124]"
                title="Открыть источник новости"
              >
                {index + 1}. {item.event.title}
                <ExternalLink className="ml-1 inline size-3 align-baseline" aria-hidden="true" />
              </a>
              <p className="mt-0.5 text-[12px] text-[#667085]">
                {item.insight ? item.insight.primary_effect : "Разбор ещё не готов"}
              </p>
              <Link
                to={insightPath}
                className="mt-1 inline-flex items-center gap-1 text-[12px] font-semibold text-[#ef3124] hover:gap-1.5"
              >
                {item.insight ? "Открыть разбор" : "Разобрать"} <ArrowRight className="size-3" />
              </Link>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

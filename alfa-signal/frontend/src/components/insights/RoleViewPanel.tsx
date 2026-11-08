import { useQuery } from "@tanstack/react-query";
import { UserRound } from "lucide-react";

import { EvidenceBadge } from "@/components/insights/EvidenceBadge";
import { InlineLoadingState } from "@/components/insights/InsightStates";
import { apiRequest } from "@/features/insights/api";
import type { EvidenceType } from "@/features/insights/model";
import { insightQueryKeys } from "@/features/insights/queries";
import { useUserRole } from "@/features/insights/role";

/* «Что это значит для вас»: ролевой слой поверх общего разбора компании
   (GET /api/v1/insights/{id}/role-view, роль — из X-User-Role). */
type ApiRoleView = {
  role: string;
  role_label: string;
  headline: string;
  points: { text: string; basis: EvidenceType }[];
  risk_order: string[];
  next_steps: { action: string; priority: "low" | "medium" | "high" }[];
  method: "llm" | "rules";
};

export function RoleViewPanel({ insightId }: { insightId: string }) {
  const [role] = useUserRole();
  const viewQuery = useQuery({
    queryKey: [...insightQueryKeys.all, "role-view", insightId, role],
    queryFn: () =>
      apiRequest<ApiRoleView>(`/api/v1/insights/${encodeURIComponent(insightId)}/role-view`),
    staleTime: Infinity,
  });
  const view = viewQuery.data;

  return (
    <section className="rounded-[12px] border border-[#e3e7eb] bg-white p-5 shadow-[0_4px_18px_rgba(37,51,68,0.025)]">
      <h2 className="flex items-center gap-2 text-[18px] font-semibold">
        <UserRound className="size-5" aria-hidden="true" /> Что это значит для вас
      </h2>
      {viewQuery.isPending ? <InlineLoadingState label="Готовим выводы для вашей роли" /> : null}
      {viewQuery.isError ? (
        <p className="mt-2 text-[13px] text-[#7b8492]">Ролевой блок сейчас недоступен.</p>
      ) : null}
      {view ? (
        <div className="mt-3 space-y-3 text-[14px]">
          <p className="text-[12px] text-[#7b8492]">
            Роль: {view.role_label}
            {view.method === "rules" ? " · собрано по правилам, без модели" : ""}
          </p>
          <p className="font-medium">{view.headline}</p>
          <ul className="space-y-2">
            {view.points.map((point) => (
              <li key={point.text} className="flex items-start gap-2">
                <EvidenceBadge type={point.basis} />
                <span>{point.text}</span>
              </li>
            ))}
          </ul>
          {view.next_steps.length ? (
            <div>
              <p className="text-[12px] font-semibold text-[#7b8492]">Ваши шаги</p>
              <ul className="mt-1 list-disc space-y-1 pl-5">
                {view.next_steps.map((step) => (
                  <li key={step.action}>{step.action}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

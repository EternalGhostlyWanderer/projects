import type { AnalysisContext } from "@/features/insights/model";

export const insightQueryKeys = {
  all: ["insights"] as const,
  workspace: (context: AnalysisContext) =>
    [...insightQueryKeys.all, "workspace", context.companyId, context.groupId] as const,
  detail: (insightId: string) => [...insightQueryKeys.all, "detail", insightId] as const,
  companies: () => [...insightQueryKeys.all, "companies"] as const,
  trace: (insightId: string) => [...insightQueryKeys.all, "trace", insightId] as const,
  chat: (insightId: string) => [...insightQueryKeys.all, "chat", insightId] as const,
};

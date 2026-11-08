/* Источник данных страниц: backend API (по умолчанию) или демо-данные (VITE_USE_DEMO=1). */
import {
  analyzeApiNews,
  askApiQuestion,
  fetchApiChatHistory,
  fetchApiCompanies,
  fetchApiInsight,
  fetchApiInsightsWorkspace,
  fetchApiTrace,
  reanalyzeApiInsight,
  sendApiFeedback,
} from "@/features/insights/apiInsightsAdapter";
import {
  fetchDemoInsight,
  fetchDemoInsightsWorkspace,
  listDemoCompanies,
} from "@/features/insights/demoInsightsAdapter";
import type {
  AnalysisContext,
  AnalysisTrace,
  BusinessInsight,
  ChatMessage,
  CompanyProfile,
  InsightsWorkspace,
} from "@/features/insights/model";

export const USE_DEMO = import.meta.env.VITE_USE_DEMO === "1";

export { PENDING_PREFIX } from "@/features/insights/apiInsightsAdapter";

export function fetchCompanies(): Promise<CompanyProfile[]> {
  return USE_DEMO ? Promise.resolve(listDemoCompanies()) : fetchApiCompanies();
}

export function fetchInsightsWorkspace(context: AnalysisContext): Promise<InsightsWorkspace> {
  return USE_DEMO ? fetchDemoInsightsWorkspace(context) : fetchApiInsightsWorkspace(context);
}

export function fetchInsight(
  insightId: string,
  companyId?: string | null,
): Promise<BusinessInsight> {
  return USE_DEMO ? fetchDemoInsight(insightId) : fetchApiInsight(insightId, companyId);
}

export function analyzeNews(
  companyId: string,
  source: { url: string } | { title: string; text: string },
): Promise<BusinessInsight> {
  if (USE_DEMO)
    return Promise.reject(new Error("Разбор новостей доступен только с подключённым backend."));
  return analyzeApiNews(companyId, source);
}

export function reanalyzeInsight(companyId: string, eventId: string): Promise<BusinessInsight> {
  if (USE_DEMO)
    return Promise.reject(new Error("Пересчёт доступен только с подключённым backend."));
  return reanalyzeApiInsight(companyId, eventId);
}

export function fetchTrace(insightId: string): Promise<AnalysisTrace | null> {
  return USE_DEMO ? Promise.resolve(null) : fetchApiTrace(insightId);
}

export function askQuestion(
  insightId: string,
  question: string,
  role?: string,
): Promise<ChatMessage> {
  if (USE_DEMO) {
    return Promise.resolve({
      role: "assistant",
      text: "AI-чат появится после подключения backend. Вопрос сохранён только в форме.",
    });
  }
  return askApiQuestion(insightId, question, role);
}

export function fetchChatHistory(insightId: string): Promise<ChatMessage[]> {
  return USE_DEMO ? Promise.resolve([]) : fetchApiChatHistory(insightId);
}

export function sendFeedback(insightId: string, useful: boolean): Promise<void> {
  return USE_DEMO ? Promise.resolve() : sendApiFeedback(insightId, useful);
}

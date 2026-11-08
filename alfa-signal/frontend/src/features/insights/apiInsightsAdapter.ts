/* Адаптер backend → модель фронтенда. Компоненты работают с теми же типами, что и в демо-режиме. */
import {
  API_BASE,
  apiRequest,
  setActiveCompany,
  type ApiChatResult,
  type ApiCompanyProfile,
  type ApiEvent,
  type ApiEvidence,
  type ApiFeedItem,
  type ApiInsight,
  type ApiTrace,
} from "@/features/insights/api";
import type {
  AnalysisContext,
  AnalysisTrace,
  BusinessInsight,
  ChatMessage,
  ChecklistItem,
  CompanyProfile,
  Evidence,
  InsightsWorkspace,
  RelevanceLevel,
} from "@/features/insights/model";
import { formatCompanyName } from "@/features/insights/companyName";
import { DEMO_AUTH, readSession } from "@/features/insights/session";

/* Компании для выбора: VITE_COMPANY_IDS="U_1,U_2" (по умолчанию — синтетические из data/synthetic). */
const COMPANY_IDS = String(
  import.meta.env.VITE_COMPANY_IDS ?? "SYN_001,SYN_002,SYN_003,SYN_004,SYN_005,SYN_006",
)
  .split(",")
  .map((id) => id.trim())
  .filter(Boolean);

export const PENDING_PREFIX = "event-";
const MANUAL_NEWS_URL = "https://alfa-signal.local/manual/";

const EVENT_TYPE_LABELS: Record<string, string> = {
  monetary_policy: "Денежно-кредитная политика",
  inflation: "Инфляция",
  macro_statistics: "Макроэкономика",
  currency: "Валюта",
  commodities: "Сырьё",
  financial_markets: "Финансовые рынки",
  regulation: "Регулирование",
  taxes: "Налоги",
  trade: "Внешняя торговля",
  sanctions: "Санкции",
  logistics: "Логистика",
  industry: "Отрасль",
  company: "Компании",
};

const FACTOR_LABELS: Record<string, string> = {
  interest_rate: "Стоимость кредитов",
  deposit_yield: "Доходность размещения средств",
  leasing_cost: "Стоимость лизинга",
  international_trade: "Внешняя торговля",
  incoming_concentration: "Зависимость от покупателей",
  outgoing_concentration: "Зависимость от поставщиков",
  industry: "Отрасль компании",
  region: "Регион присутствия",
  trade_country: "Страна внешней торговли",
};

const PRODUCT_LABELS: Record<string, string> = {
  loa: "Кредитные продукты",
  dep: "Депозиты",
  lea: "Лизинг",
  gar: "Банковские гарантии",
  rko: "Расчётный счёт",
  zpp: "Зарплатный проект",
};

const PRODUCT_SENSITIVITY: Record<string, string> = {
  loa: "Стоимость финансирования",
  dep: "Доходность размещения средств",
  lea: "Стоимость лизинга",
};

const MISSING_LABELS: Record<string, string> = {
  "financials.revenue_rub": "Выручка компании",
  "industry.name": "Отрасль",
  "location.region": "Регион",
  "foreign_trade.country": "Страна внешней торговли",
};

function companyHeaders(companyId: string): HeadersInit {
  return { "X-Company-Id": companyId };
}

function categoryLabel(eventType: string | null | undefined): string {
  return (eventType && EVENT_TYPE_LABELS[eventType]) || "Экономика";
}

function attentionLabel(kind: string, level: RelevanceLevel): string {
  if (kind === "opportunity") return "Возможность";
  return level === "high" ? "Высокая значимость" : "Средняя значимость";
}

function documentUrl(chunkId: string, page?: number | null): string | undefined {
  const separator = chunkId.lastIndexOf("-p");
  if (separator <= 0) return undefined;
  const docId = chunkId.slice(0, separator);
  // PDF открывается обычной ссылкой, без заголовка Authorization: токен — в адресе (только для файла).
  const token = readSession()?.access_token;
  const query = token ? `?access_token=${encodeURIComponent(token)}` : "";
  return `${API_BASE}/api/v1/research/documents/${docId}/file${query}${page ? `#page=${page}` : ""}`;
}

function adaptEvidence(item: ApiEvidence): Evidence {
  const isBank = item.source_kind === "bank_research";
  const isManualNews = item.source_url?.startsWith(MANUAL_NEWS_URL);
  return {
    id: item.id,
    type: item.type,
    text: item.text,
    sourceId: item.source_id ?? undefined,
    sourceTitle: item.source_title ?? undefined,
    sourceUrl: isBank
      ? documentUrl(item.source_id ?? "", item.source_page)
      : isManualNews
        ? undefined
        : (item.source_url ?? undefined),
    sourceDate: item.source_date ?? undefined,
    sourcePage: item.source_page ? String(item.source_page) : undefined,
  };
}

export function adaptApiInsight(insight: ApiInsight, event?: ApiEvent | null): BusinessInsight {
  const evidence = insight.evidence.map(adaptEvidence);
  const title = event?.title ?? insight.event_summary[0]?.text ?? insight.primary_effect.text;
  return {
    id: insight.insight_id,
    companyId: insight.company_id,
    groupId: null,
    title,
    detailTitle: title,
    category: categoryLabel(event?.event_type),
    publishedAt: event?.published_at ?? insight.created_at,
    analyzedAt: insight.created_at,
    relevanceLevel: insight.relevance.level,
    kind: insight.kind,
    eventSummary: insight.event_summary.map((claim) => claim.text).join(" "),
    cardSummary: insight.primary_effect.text,
    attentionLabel: attentionLabel(insight.kind, insight.relevance.level),
    provenanceLabel:
      insight.bank_view.status === "found"
        ? "Есть позиция Альфа-Банка"
        : "Позиция банка не установлена",
    cardCaveat: insight.unknowns[0] ? `Неизвестно: ${insight.unknowns[0]}` : undefined,
    relevanceReasons: insight.relevance.reasons.map((claim) => claim.text),
    decisionQuestion: insight.decision_question,
    impact: {
      mechanism: insight.mechanism.join(" → "),
      primaryEffect: insight.primary_effect.text,
      risks: insight.risks.map((risk) => `${risk.title}: ${risk.text}`),
      opportunities: insight.opportunities.map((item) => `${item.title}: ${item.text}`),
      nextSteps: insight.next_steps.map((step) => step.action),
      unknowns: insight.unknowns,
      evidenceIds: evidence.map((item) => item.id),
    },
    evidence,
    eventId: insight.event_id,
    ...translationFields(event),
    eventSources: event?.sources?.map(({ url, source }) => ({ url, source })),
    mechanismSteps: insight.mechanism,
    bankView: {
      status: insight.bank_view.status,
      claims: insight.bank_view.claims.map((claim) => ({
        text: claim.text,
        evidenceIds: claim.evidence_ids,
      })),
    },
    qualityStatus: insight.quality_status,
    qualityIssues: insight.quality_issues,
    traceId: insight.trace_id,
  };
}

// Автоматическая проверка: числа и ссылки на источники, актуальность прогнозов банка, спорные цифры.
const PROVENANCE_LABELS: Partial<Record<string, string>> = {
  verified: "Проверено автоматически",
  outdated: "Позиция банка могла устареть",
  conflicting: "Источники расходятся",
};

/* Перевод иностранной новости: оригинал заголовка — для пометки «перевод с английского». */
function translationFields(
  event?: ApiEvent | null,
): Pick<BusinessInsight, "originalTitle" | "untranslated"> {
  if (event?.language !== "en") return {};
  if (event.original_title && event.original_title !== event.title) {
    return { originalTitle: event.original_title };
  }
  return { untranslated: !event.original_title };
}

function adaptFeedItem(item: ApiFeedItem, companyId: string): BusinessInsight {
  const { event, relevance, insight } = item;
  const reasons = relevance.matched_factors.map((factor) => FACTOR_LABELS[factor] ?? factor);
  const breakdown = (relevance.components ?? []).map(
    (part) =>
      `${part.label} +${part.points}: ${part.reason}${part.certainty === "hypothesis" ? " (гипотеза)" : ""}`,
  );
  const age = relevance.freshness?.age_days;
  if (breakdown.length && age !== null && age !== undefined && relevance.freshness) {
    breakdown.push(
      `Свежесть: ${age < 1 ? "меньше суток" : `${Math.round(age)} дн.`} (порядок в ленте ×${relevance.freshness.factor})`,
    );
  }
  const relatedCount = item.related_count ?? 0;
  if (relatedCount > 0) {
    const titles = (item.related ?? []).map((related) => `«${related.title}»`).join(", ");
    breakdown.push(`По этому сюжету ещё ${relatedCount} публ.: ${titles}`);
  }
  const scoredLevel =
    relevance.level && relevance.level !== "none" ? (relevance.level as RelevanceLevel) : undefined;
  const level: RelevanceLevel =
    scoredLevel ?? insight?.level ?? (relevance.match_count >= 2 ? "high" : "medium");
  return {
    id: insight ? insight.insight_id : `${PENDING_PREFIX}${event.event_id}`,
    companyId,
    groupId: null,
    title: event.title,
    category: categoryLabel(event.event_type),
    publishedAt: event.published_at ?? new Date().toISOString(),
    relevanceLevel: level,
    kind: insight?.kind ?? "mixed",
    eventSummary: event.summary ?? event.title,
    cardSummary: insight?.primary_effect ?? event.summary ?? event.title,
    attentionLabel: insight ? attentionLabel(insight.kind, level) : "Не разобрано",
    provenanceLabel: insight
      ? (PROVENANCE_LABELS[insight.quality_status] ?? "Разбор агента готов")
      : item.preparing
        ? "Готовится разбор…"
        : "Нажмите, чтобы запустить анализ",
    cardCaveat: breakdown.length
      ? `Почему в ленте: ${(relevance.components ?? []).map((part) => part.reason).join("; ")}` +
        (relatedCount > 0 ? ` · ещё ${relatedCount} публ. по сюжету` : "")
      : reasons.length
        ? `Совпадения: ${reasons.join(", ")}`
        : undefined,
    relevanceReasons: breakdown.length ? breakdown : reasons,
    relevanceScore: relevance.score,
    relevanceBreakdown: breakdown,
    eventSources: event.sources?.map(({ url, source }) => ({ url, source })),
    decisionQuestion: "",
    impact: {
      mechanism: "",
      primaryEffect: "",
      risks: [],
      opportunities: [],
      nextSteps: [],
      unknowns: [],
      evidenceIds: [],
    },
    evidence: [],
    eventId: event.event_id,
    qualityStatus: insight?.quality_status,
    ...translationFields(event),
    riskCount: insight?.risk_count,
    opportunityCount: insight?.opportunity_count,
    isPending: !insight,
  };
}

function adaptCompany(profile: ApiCompanyProfile): CompanyProfile {
  const enabledProducts = Object.entries(profile.products)
    .filter(([, enabled]) => enabled)
    .map(([key]) => key);
  const features = enabledProducts.map((key) => PRODUCT_LABELS[key]).filter(Boolean);
  if (profile.risk_indicators.fts_data_available && profile.risk_indicators.fts_country) {
    features.push(`Внешняя торговля: ${profile.risk_indicators.fts_country}`);
  }
  if (profile.group_id) features.push("Входит в группу компаний");

  const sensitivity = enabledProducts.map((key) => PRODUCT_SENSITIVITY[key]).filter(Boolean);
  if (profile.risk_indicators.fts_country) sensitivity.push("Сроки международных расчётов");

  return {
    companyId: profile.id,
    groupId: profile.group_id,
    name: formatCompanyName(profile.id),
    industry: profile.industry.name ?? "Отрасль не указана",
    region: profile.location.region ?? "Регион не указан",
    profileLabel: "Профиль по данным банка",
    businessFeatures: features.length ? features : ["Нет данных о продуктах"],
    sensitivityFactors: sensitivity.length ? sensitivity : ["Не определены"],
    missingData: profile.data_quality.missing_fields.map((field) => MISSING_LABELS[field] ?? field),
    contextSources: ["Данные компании", "Платёжные связи"],
  };
}

export async function fetchApiCompanies(): Promise<CompanyProfile[]> {
  // При демо-входе — компании пользователя, если они заданы в DEMO_USERS на сервере.
  const sessionCompanies = DEMO_AUTH ? (readSession()?.companies ?? []) : [];
  const companyIds = sessionCompanies.length ? sessionCompanies : COMPANY_IDS;
  const results = await Promise.allSettled(
    companyIds.map((id) =>
      apiRequest<ApiCompanyProfile>(`/api/v1/companies/${encodeURIComponent(id)}/profile`),
    ),
  );
  const companies = results
    .filter(
      (result): result is PromiseFulfilledResult<ApiCompanyProfile> =>
        result.status === "fulfilled",
    )
    .map((result) => adaptCompany(result.value));
  if (!companies.length) {
    throw new Error("Компании не найдены: проверьте VITE_COMPANY_IDS и данные backend.");
  }
  return companies;
}

export async function fetchApiInsightsWorkspace(
  context: AnalysisContext,
): Promise<InsightsWorkspace> {
  const companyId = context.companyId;
  setActiveCompany(companyId);
  const [profile, feed] = await Promise.all([
    apiRequest<ApiCompanyProfile>(`/api/v1/companies/${encodeURIComponent(companyId)}/profile`),
    apiRequest<{ items: ApiFeedItem[]; preanalysis?: { running: boolean } }>(
      `/api/v1/feed?company_id=${encodeURIComponent(companyId)}&limit=40`,
      {
        headers: companyHeaders(companyId),
      },
    ),
  ]);
  const company = adaptCompany(profile);
  const insights = feed.items.map((item) => adaptFeedItem(item, companyId));

  const topItem = feed.items.find((item) => item.insight);
  const topAnalyzed = topItem?.insight;
  let checklist: ChecklistItem[] = company.missingData.slice(0, 2).map((item) => ({
    title: item,
    description: "Уточните этот показатель — без него оценка влияния событий менее точная.",
  }));
  let priorityAction: InsightsWorkspace["priorityAction"] = null;

  if (topAnalyzed) {
    const full = await apiRequest<ApiInsight>(`/api/v1/insights/${topAnalyzed.insight_id}`, {
      headers: companyHeaders(companyId),
    });
    if (full.next_steps.length) {
      // Шаги из разбора самого важного события ленты; вопрос для решения — один раз, у первого шага.
      checklist = full.next_steps.slice(0, 2).map((step, index) => ({
        title: step.action,
        description:
          index === 0
            ? full.decision_question
            : `По событию «${topItem?.event.title ?? "из ленты"}»`,
      }));
      priorityAction = {
        companyId,
        insightId: full.insight_id,
        title: full.next_steps[0].action,
        rationale: full.decision_question,
      };
    }
  }

  return {
    context,
    company,
    insights,
    priorityAction,
    checklist,
    preanalysisRunning: Boolean(feed.preanalysis?.running),
  };
}

/* Готовый инсайт или запуск анализа для события из ленты (id вида "event-<event_id>"). */
export async function fetchApiInsight(
  insightId: string,
  companyId?: string | null,
): Promise<BusinessInsight> {
  let insight: ApiInsight;
  if (insightId.startsWith(PENDING_PREFIX)) {
    if (!companyId) throw new Error("Не выбрана компания для анализа.");
    insight = await apiRequest<ApiInsight>("/api/v1/insights/analyze", {
      method: "POST",
      headers: companyHeaders(companyId),
      body: JSON.stringify({
        company_id: companyId,
        event_id: insightId.slice(PENDING_PREFIX.length),
      }),
    });
  } else {
    insight = await apiRequest<ApiInsight>(`/api/v1/insights/${encodeURIComponent(insightId)}`, {
      headers: companyId ? companyHeaders(companyId) : undefined,
    });
  }
  const event = await apiRequest<ApiEvent>(
    `/api/v1/events/${encodeURIComponent(insight.event_id)}`,
  ).catch(() => null);
  return adaptApiInsight(insight, event);
}

/* Пересчитать сохранённый анализ события (платно: агент запускается заново). */
export async function reanalyzeApiInsight(
  companyId: string,
  eventId: string,
): Promise<BusinessInsight> {
  const insight = await apiRequest<ApiInsight>("/api/v1/insights/analyze", {
    method: "POST",
    headers: companyHeaders(companyId),
    body: JSON.stringify({ company_id: companyId, event_id: eventId, force: true }),
  });
  return adaptApiInsight(insight);
}

/* «Разобрать новость»: ссылка или вставленный текст → новый инсайт. */
export async function analyzeApiNews(
  companyId: string,
  source: { url: string } | { title: string; text: string },
): Promise<BusinessInsight> {
  const insight = await apiRequest<ApiInsight>("/api/v1/insights/analyze", {
    method: "POST",
    headers: companyHeaders(companyId),
    body: JSON.stringify({ company_id: companyId, ...source }),
  });
  return adaptApiInsight(insight);
}

export async function fetchApiTrace(insightId: string): Promise<AnalysisTrace> {
  const trace = await apiRequest<ApiTrace>(
    `/api/v1/insights/${encodeURIComponent(insightId)}/trace`,
  );
  return {
    traceId: trace.trace_id,
    toolCalls: trace.tool_calls,
    rounds: trace.rounds,
    steps: trace.steps.map((step) => ({
      n: step.n,
      phase: step.phase,
      name: step.name,
      status: step.status,
      reason: step.reason,
      outputSummary: step.output_summary,
      error: step.error,
    })),
  };
}

export async function askApiQuestion(
  insightId: string,
  question: string,
  role?: string,
): Promise<ChatMessage> {
  const result = await apiRequest<ApiChatResult>(
    `/api/v1/insights/${encodeURIComponent(insightId)}/ask`,
    {
      method: "POST",
      body: JSON.stringify({ question, role }),
    },
  );
  return {
    role: "assistant",
    text: result.answer.map((claim) => claim.text).join(" "),
    claims: result.answer.map((claim) => ({
      text: claim.text,
      basis: claim.basis,
      evidenceIds: claim.evidence_ids,
    })),
    followUps: result.follow_up_questions,
  };
}

export async function fetchApiChatHistory(insightId: string): Promise<ChatMessage[]> {
  const history = await apiRequest<{ items: Array<{ role: "user" | "assistant"; text: string }> }>(
    `/api/v1/insights/${encodeURIComponent(insightId)}/chat`,
  );
  return history.items.map((item) => ({ role: item.role, text: item.text }));
}

export async function sendApiFeedback(insightId: string, useful: boolean): Promise<void> {
  await apiRequest<void>(`/api/v1/insights/${encodeURIComponent(insightId)}/feedback`, {
    method: "POST",
    body: JSON.stringify({ useful }),
  });
}

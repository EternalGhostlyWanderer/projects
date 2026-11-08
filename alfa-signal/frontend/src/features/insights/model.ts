export type EvidenceType = "FACT" | "BANK_ANALYSIS" | "AI_INFERENCE" | "HYPOTHESIS";

export type RelevanceLevel = "low" | "medium" | "high";

export type InsightKind = "risk" | "opportunity" | "mixed";

export interface Evidence {
  id: string;
  type: EvidenceType;
  text: string;
  sourceId?: string;
  sourceTitle?: string;
  sourceUrl?: string;
  sourceDate?: string;
  sourcePage?: string;
}

export interface BusinessImpact {
  mechanism: string;
  primaryEffect: string;
  risks: string[];
  opportunities: string[];
  nextSteps: string[];
  unknowns: string[];
  evidenceIds: string[];
}

export interface BusinessInsight {
  id: string;
  companyId: string;
  groupId: string | null;
  title: string;
  detailTitle?: string;
  category: string;
  publishedAt: string;
  analyzedAt?: string;
  relevanceLevel: RelevanceLevel;
  kind: InsightKind;
  eventSummary: string;
  cardSummary: string;
  attentionLabel: string;
  provenanceLabel: string;
  cardCaveat?: string;
  relevanceReasons: string[];
  decisionQuestion: string;
  impact: BusinessImpact;
  evidence: Evidence[];
  /* Поля ниже заполняются только при работе с API (backend). */
  eventId?: string;
  /* Балл релевантности 0–100 и его разложение: «фактор +баллы: причина». */
  relevanceScore?: number;
  relevanceBreakdown?: string[];
  /* Все издания, написавшие о событии (после склейки дублей). */
  eventSources?: { url: string; source: string }[];
  mechanismSteps?: string[];
  bankView?: BankView;
  qualityStatus?: QualityStatus;
  qualityIssues?: string[];
  traceId?: string | null;
  /* Новость иностранного издания: заголовок переведён, оригинал — originalTitle. */
  originalTitle?: string;
  /* Заголовок ещё не переведён (нет ключа LLM): показывается как есть, на английском. */
  untranslated?: boolean;
  /* Число рисков и возможностей из разбора — для карточки ленты, где полного impact нет. */
  riskCount?: number;
  opportunityCount?: number;
  /* Событие из ленты, которое ещё не разбиралось агентом: анализ запускается по клику. */
  isPending?: boolean;
}

/* verified — проверено автоматически (числа и ссылки на источники, актуальность прогнозов банка),
   а не экспертная оценка вывода; outdated — позиция банка могла устареть; conflicting — источники расходятся. */
export type QualityStatus =
  "unverified" | "verified" | "partial" | "outdated" | "conflicting" | "failed";

export interface BankView {
  status: "found" | "not_found";
  claims: Array<{ text: string; evidenceIds: string[] }>;
}

export interface ChatClaim {
  text: string;
  basis: EvidenceType;
  evidenceIds: string[];
}

export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  claims?: ChatClaim[];
  followUps?: string[];
}

export interface TraceStep {
  n: number;
  phase: string;
  name: string;
  status: "ok" | "error" | "skipped";
  reason?: string | null;
  outputSummary: string;
  error?: string | null;
}

export interface AnalysisTrace {
  traceId: string;
  toolCalls: number;
  rounds: number;
  steps: TraceStep[];
}

export interface ChecklistItem {
  title: string;
  description: string;
}

export interface CompanyProfile {
  companyId: string;
  groupId: string | null;
  name: string;
  industry: string;
  region: string;
  profileLabel: string;
  businessFeatures: string[];
  sensitivityFactors: string[];
  missingData: string[];
  contextSources: string[];
}

export interface PriorityAction {
  companyId: string;
  insightId: string;
  title: string;
  rationale: string;
}

export interface AnalysisContext {
  companyId: string;
  groupId: string | null;
}

export interface InsightsWorkspace {
  context: AnalysisContext;
  company: CompanyProfile;
  insights: BusinessInsight[];
  priorityAction: PriorityAction | null;
  /* Блок «Сначала проверьте» (API-режим); в демо-режиме не заполняется. */
  checklist?: ChecklistItem[];
  /* Идёт фоновый разбор верхних событий ленты: лента обновляется чаще, пока он не закончится. */
  preanalysisRunning?: boolean;
}

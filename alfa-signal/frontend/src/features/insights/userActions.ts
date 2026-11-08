/* Действия пользователя: данные о компании, заявки менеджеру и аналитику, скрытие событий. */
import { apiRequest } from "@/features/insights/api";
import { USE_DEMO } from "@/features/insights/dataSource";

export interface CompanyUserData {
  floating_debt_rub?: number | null;
  fixed_debt_rub?: number | null;
  contract_currencies?: string[];
  trade_countries?: string[];
  key_inputs?: string | null;
  export_share_pct?: number | null;
  revenue_currencies?: string[];
  customer_industries?: string[];
  supplier_industries?: string[];
  investment_plans?: string | null;
  borrowing_plans?: string | null;
  covenants?: string | null;
  /* Темы, важные компании: учитываются в ленте отдельной группой «Интересы компании». */
  interests?: string[];
  note?: string | null;
  /* Откуда поле: вручную или из документа (с цитатой). */
  field_sources?: Record<string, FieldSource>;
  updated_at?: string;
}

export interface FieldSource {
  source: "manual" | "document";
  document?: string | null;
  quote?: string | null;
  updated_at?: string | null;
  user_id?: string | null;
}

export interface ExtractedField {
  field: string;
  label: string;
  value: unknown;
  quote: string;
}

export interface DocumentPreview {
  document: string;
  document_type: string;
  truncated: boolean;
  fields: ExtractedField[];
  rejected: { field: string; reason: string }[];
}

export interface RelatedCompany {
  company_id: string;
  okved_name: string | null;
  region: string | null;
  link: "group" | "shared_person";
  certainty: "confirmed" | "hypothesis";
  basis: string;
}

export interface CompanyLinks {
  group: {
    group_id: string | null;
    company_count: number;
    revenue_rub: number | null;
    revenue_complete: boolean;
    large_business: boolean;
  };
  related_companies: RelatedCompany[];
  counterparty_industries: {
    status: string;
    industries: {
      okved_class: string;
      example_name: string | null;
      direction: "incoming" | "outgoing";
      share: number;
    }[];
    unknown_share: number | null;
  };
}

export interface ApiCompanyProfileFull {
  id: string;
  industry: { code: string | null; name: string | null };
  location: { city: string | null; region: string | null };
  financials: { revenue_rub: number | null; employees_fns: string | null };
  risk_indicators: {
    fts_data_available: boolean;
    fts_country: string | null;
    factoring_product: boolean;
  };
  products: Record<string, boolean>;
  client_type: string | null;
  data_quality: { missing_fields: string[] };
  /* Положение в отрасли по выборке банка (backend position.py). */
  industry_position?: {
    status: string;
    rank?: number;
    peers?: number;
    share_of_sample?: number;
    tier_label?: string;
    group?: { rank: number; players: number; share_of_sample: number };
  };
}

const headers = (companyId: string) => ({ "X-Company-Id": companyId });
const demoOnly = () => Promise.reject(new Error("Доступно только с подключённым backend."));

export function fetchCompanyProfileFull(companyId: string): Promise<ApiCompanyProfileFull> {
  if (USE_DEMO) return demoOnly();
  return apiRequest(`/api/v1/companies/${encodeURIComponent(companyId)}/profile`);
}

export function fetchCompanyLinks(companyId: string): Promise<CompanyLinks> {
  if (USE_DEMO) return demoOnly();
  return apiRequest(`/api/v1/companies/${encodeURIComponent(companyId)}/links`, {
    headers: headers(companyId),
  });
}

export async function fetchUserData(companyId: string): Promise<CompanyUserData> {
  if (USE_DEMO) return {};
  const result = await apiRequest<{ data: CompanyUserData }>(
    `/api/v1/companies/${encodeURIComponent(companyId)}/user-data`,
    { headers: headers(companyId) },
  );
  return result.data;
}

export async function saveUserData(
  companyId: string,
  data: CompanyUserData,
): Promise<CompanyUserData> {
  if (USE_DEMO) return demoOnly();
  const result = await apiRequest<{ data: CompanyUserData }>(
    `/api/v1/companies/${encodeURIComponent(companyId)}/user-data`,
    { method: "PUT", headers: headers(companyId), body: JSON.stringify(data) },
  );
  return result.data;
}

export async function sendClientRequest(
  companyId: string,
  insightId: string,
  kind: "manager_callback" | "analyst_question",
  options: { text?: string; role?: string } = {},
): Promise<string> {
  if (USE_DEMO) return "Демо-режим: заявка не отправлена.";
  const result = await apiRequest<{ message: string }>(
    `/api/v1/insights/${encodeURIComponent(insightId)}/requests`,
    {
      method: "POST",
      headers: headers(companyId),
      body: JSON.stringify({ kind, ...options }),
    },
  );
  return result.message;
}

export function setEventHidden(companyId: string, eventId: string, hidden: boolean): Promise<void> {
  if (USE_DEMO) return Promise.resolve();
  return apiRequest(`/api/v1/feed/hidden`, {
    method: "POST",
    headers: headers(companyId),
    body: JSON.stringify({ company_id: companyId, event_id: eventId, hidden }),
  });
}

export interface DigestItem {
  event: {
    event_id: string;
    title: string;
    published_at: string | null;
    url: string;
    source?: string;
  };
  relevance: { score?: number; explanation?: string };
  insight: { insight_id: string; primary_effect: string } | null;
}

/* Сводка: главные события за период (вебинар, вопрос 60). */
export async function fetchDigest(
  companyId: string,
  hours: number,
): Promise<{ hours: number; items: DigestItem[] }> {
  if (USE_DEMO) return { hours, items: [] };
  return apiRequest(
    `/api/v1/feed/digest?company_id=${encodeURIComponent(companyId)}&hours=${hours}&limit=3`,
    { headers: headers(companyId) },
  );
}

/* «Обновить ленту»: сбор RSS и предварительный анализ важного запускаются на сервере в фоне. */
export async function refreshFeed(): Promise<boolean> {
  if (USE_DEMO) return false;
  const result = await apiRequest<{ started: boolean }>("/api/v1/events/refresh", {
    method: "POST",
  });
  return result.started;
}

/* Предпросмотр полей из документа (платно, модель extract); ничего не сохраняет. */
export async function extractFromDocument(
  companyId: string,
  body: { filename: string; text?: string; file_base64?: string },
): Promise<DocumentPreview> {
  if (USE_DEMO) return demoOnly();
  return apiRequest<DocumentPreview>(
    `/api/v1/companies/${encodeURIComponent(companyId)}/user-data/extract`,
    { method: "POST", headers: headers(companyId), body: JSON.stringify(body) },
  );
}

/* Сохранить выбранные пользователем поля из документа — с источником и цитатой. */
export async function applyDocumentFields(
  companyId: string,
  document: string,
  fields: ExtractedField[],
): Promise<CompanyUserData> {
  if (USE_DEMO) return demoOnly();
  const result = await apiRequest<{ data: CompanyUserData }>(
    `/api/v1/companies/${encodeURIComponent(companyId)}/user-data/apply-document`,
    {
      method: "POST",
      headers: headers(companyId),
      body: JSON.stringify({
        document,
        fields: fields.map(({ field, value, quote }) => ({ field, value, quote })),
      }),
    },
  );
  return result.data;
}

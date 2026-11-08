/* Типы ответов backend (snake_case, см. docs/api.md) и HTTP-клиент. */
import type { EvidenceType, QualityStatus, RelevanceLevel } from "@/features/insights/model";
import { currentRole } from "@/features/insights/role";
import {
  expireSession,
  readSession,
  saveSession,
  type DemoSession,
} from "@/features/insights/session";

export const API_BASE = String(import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");

export interface ApiClaim {
  text: string;
  basis: EvidenceType;
  evidence_ids: string[];
  confidence: RelevanceLevel;
}

export interface ApiEvidence {
  id: string;
  type: EvidenceType;
  text: string;
  source_kind: "news" | "company_data" | "bank_research" | "model";
  source_id?: string | null;
  source_title?: string | null;
  source_url?: string | null;
  source_date?: string | null;
  source_page?: number | null;
}

export interface ApiInsight {
  insight_id: string;
  company_id: string;
  event_id: string;
  kind: "risk" | "opportunity" | "mixed";
  relevance: { score: number; level: RelevanceLevel; reasons: ApiClaim[] };
  event_summary: ApiClaim[];
  mechanism: string[];
  direction: string;
  primary_effect: ApiClaim;
  risks: Array<ApiClaim & { title: string; severity: RelevanceLevel }>;
  opportunities: Array<ApiClaim & { title: string; potential: RelevanceLevel }>;
  scenarios: Array<{ name: string; condition: string; outcome: ApiClaim }>;
  bank_view: { status: "found" | "not_found"; claims: ApiClaim[] };
  next_steps: Array<{ action: string; priority: RelevanceLevel }>;
  unknowns: string[];
  decision_question: string;
  evidence: ApiEvidence[];
  trace_id: string | null;
  model: string;
  created_at: string;
  quality_status: QualityStatus;
  quality_issues: string[];
}

export interface ApiEvent {
  event_id: string;
  title: string;
  published_at: string | null;
  source: string;
  url: string;
  summary: string | null;
  event_type: string | null;
  impact_channels: string[];
  /* Иностранные издания: язык оригинала и оригинальный заголовок (title — перевод на русский). */
  language?: "ru" | "en" | null;
  original_title?: string | null;
  /* Склейка публикаций: все издания, написавшие о событии (может отсутствовать в старых данных). */
  sources?: {
    url: string;
    source: string;
    title: string;
    summary?: string | null;
    published_at: string | null;
  }[];
  has_update?: boolean;
}

export interface ApiFeedItem {
  event: ApiEvent;
  /* Событие стоит в фоновом разборе (backend scheduler.request_preanalysis). */
  preparing?: boolean;
  /* Публикации того же сюжета (комментарии, реакция ведомств) — под этой карточкой. */
  related_count?: number;
  related?: { event_id: string; title: string; source: string; url: string; score: number }[];
  relevance: {
    matched_factors: string[];
    match_count: number;
    /* Объяснимый балл 0–100 (backend scoring.py): сумма components равна score. */
    score?: number;
    level?: "high" | "medium" | "low" | "none";
    explanation?: string;
    /* Свежесть влияет только на порядок в ленте: rank = score × factor. */
    freshness?: { factor: number; age_days: number | null };
    rank?: number;
    components?: {
      group: string;
      label: string;
      points: number;
      max: number;
      reason: string;
      certainty: "confirmed" | "potential" | "hypothesis";
    }[];
  };
  insight: {
    insight_id: string;
    kind: "risk" | "opportunity" | "mixed";
    score: number;
    level: RelevanceLevel;
    primary_effect: string;
    quality_status: QualityStatus;
    risk_count?: number;
    opportunity_count?: number;
  } | null;
}

export interface ApiCompanyProfile {
  id: string;
  industry: { code: string | null; name: string | null };
  location: { city: string | null; region: string | null };
  financials: { revenue_rub: number | null };
  risk_indicators: { fts_data_available: boolean; fts_country: string | null };
  products: Record<string, boolean>;
  group_id: string | null;
  data_quality: { missing_fields: string[] };
}

export interface ApiTrace {
  trace_id: string;
  tool_calls: number;
  rounds: number;
  steps: Array<{
    n: number;
    phase: string;
    name: string;
    status: "ok" | "error" | "skipped";
    reason: string | null;
    output_summary: string;
    error: string | null;
  }>;
}

export interface ApiChatResult {
  answer: ApiClaim[];
  follow_up_questions: string[];
}

const STATUS_MESSAGES: Record<number, string> = {
  429: "Дневной лимит анализа исчерпан, сброс в 03:00 МСК.",
  502: "Модель не ответила. Попробуйте повторить.",
  503: "Сервис анализа недоступен: не настроен ключ LLM или нет данных компаний.",
};

/* Кто смотрит: у каждого сотрудника своя лента, скрытые события и чат (docs/api.md, «Пользователи и роли»). */
function userHeaders(): Record<string, string> {
  const session = readSession();
  const userId = session?.user_id;
  return {
    "X-User-Role": currentRole(),
    ...(userId ? { "X-User-Id": userId } : {}),
    ...(session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}),
  };
}

/* Контекст компании для каждого запроса: backend в строгом режиме (API_REQUIRE_COMPANY_SCOPE=1) без него
   не отдаёт данные компании. Компания — из адреса запроса, иначе — выбранная сейчас. */
let activeCompanyId: string | null = null;

export function setActiveCompany(companyId: string | null): void {
  activeCompanyId = companyId;
}

function companyFromPath(path: string): string | null {
  const fromPath = /\/companies\/([^/?]+)/.exec(path)?.[1];
  const fromQuery = /[?&]company_id=([^&]+)/.exec(path)?.[1];
  const value = fromPath ?? fromQuery;
  return value ? decodeURIComponent(value) : activeCompanyId;
}

function companyHeader(path: string): Record<string, string> {
  const companyId = companyFromPath(path);
  return companyId ? { "X-Company-Id": companyId } : {};
}

/* Скользящая сессия: после половины срока токена (refresh_after) любой запрос с открытой страницы
   сначала продлевает его. Лента перезапрашивается раз в 5 минут, поэтому, пока сайт открыт,
   сессия не истекает; закрытый дольше срока сайт попросит войти снова. */
const REFRESH_RETRY_MS = 60_000;
let refreshing: Promise<void> | null = null;
let lastRefreshAttempt = 0;

async function renewSessionIfDue(): Promise<void> {
  const session = readSession();
  if (!session?.access_token || !session.refresh_after) return;
  const now = Date.now();
  if (session.refresh_after * 1000 > now || now - lastRefreshAttempt < REFRESH_RETRY_MS) return;
  lastRefreshAttempt = now;
  refreshing ??= (async () => {
    try {
      const renewed = await apiRequest<DemoSession>("/api/v1/auth/refresh", { method: "POST" });
      saveSession({
        ...session,
        access_token: renewed.access_token,
        expires_at: renewed.expires_at,
        refresh_after: renewed.refresh_after,
        role: renewed.role,
        companies: renewed.companies,
        name: renewed.name,
      });
    } catch {
      /* не продлили (сеть, сервер) — текущий токен ещё действует, повторим через минуту */
    } finally {
      refreshing = null;
    }
  })();
  await refreshing;
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  if (!path.startsWith("/api/v1/auth/")) await renewSessionIfDue();
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...companyHeader(path),
        ...userHeaders(),
        ...init?.headers,
      },
    });
  } catch {
    throw new Error("Сервер Альфа Сигнала недоступен. Проверьте, что backend запущен.");
  }

  if (
    response.status === 401 &&
    (!path.startsWith("/api/v1/auth/") || path === "/api/v1/auth/refresh")
  ) {
    // Сессия истекла или отозвана (например, сменился секрет на сервере): снова на экран входа.
    expireSession();
    throw new Error("Сессия истекла, войдите снова.");
  }

  if (!response.ok) {
    let detail: string;
    try {
      const body = (await response.json()) as { detail?: unknown };
      detail =
        typeof body.detail === "string"
          ? body.detail
          : typeof body.detail === "object" && body.detail && "message" in body.detail
            ? String((body.detail as { message: unknown }).message)
            : "";
    } catch {
      detail = "";
    }
    // Причина от сервера важнее общей фразы: «Модель не ответила: ключ не принят» сразу говорит,
    // что чинить. Общая фраза — только если сервер причину не прислал.
    throw new Error(
      (detail && detail.slice(0, 400)) ||
        STATUS_MESSAGES[response.status] ||
        `Ошибка сервера (${response.status})`,
    );
  }

  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

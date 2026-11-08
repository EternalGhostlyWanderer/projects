import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  Check,
  ChevronRight,
  ExternalLink,
  FileText,
  Send,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { AnalysisTrace } from "@/components/insights/AnalysisTrace";
import { CompanyProfilePanel } from "@/components/insights/CompanyProfilePanel";
import { RoleViewPanel } from "@/components/insights/RoleViewPanel";
import { Disclaimer } from "@/components/insights/Disclaimer";
import { EvidenceBadge } from "@/components/insights/EvidenceBadge";
import {
  InlineLoadingState,
  InsightErrorState,
  InsightLoadingState,
} from "@/components/insights/InsightStates";
import { Input } from "@/components/ui/input";
import {
  askQuestion,
  fetchChatHistory,
  fetchCompanies,
  fetchInsight,
  PENDING_PREFIX,
  reanalyzeInsight,
  sendFeedback,
  USE_DEMO,
} from "@/features/insights/dataSource";
import type { BusinessInsight, ChatMessage, Evidence } from "@/features/insights/model";
import { formatCompanyName } from "@/features/insights/companyName";
import { insightQueryKeys } from "@/features/insights/queries";
import { currentRole } from "@/features/insights/role";
import { sendClientRequest } from "@/features/insights/userActions";

const dateFormatter = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric",
  month: "long",
});

const analyzedAtFormatter = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric",
  month: "long",
  hour: "2-digit",
  minute: "2-digit",
});

const DEMO_CHECK_ITEMS = ["Дата пересмотра ставки", "План новых заимствований"];
const QUALITY_LABELS: Record<string, string> = {
  verified: "Проверено автоматически",
  partial: "Нужно учесть ограничения",
  outdated: "Позиция банка могла устареть",
  conflicting: "Источники расходятся",
  unverified: "Требует проверки",
  failed: "Не удалось проверить",
};
const EVIDENCE_TITLES: Record<Evidence["type"], string> = {
  FACT: "Факт",
  BANK_ANALYSIS: "Аналитика банка",
  AI_INFERENCE: "Ответ ИИ",
  HYPOTHESIS: "Требует проверки",
};
const SOURCE_GROUPS = ["Событие", "Данные компании", "Аналитика банка", "Методика"] as const;
const SOURCE_PREVIEW_COUNT = 3;

export function InsightDetailsPage() {
  const { insightId = "" } = useParams<{ insightId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const companyParam = searchParams.get("company");
  const isPendingEvent = insightId.startsWith(PENDING_PREFIX);

  const [checkedItems, setCheckedItems] = useState<string[]>([]);
  const [question, setQuestion] = useState("");
  const [questionStatus, setQuestionStatus] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [feedback, setFeedback] = useState<"yes" | "no" | null>(null);
  const [isCheckSaved, setIsCheckSaved] = useState(false);
  const [isMethodOpen, setIsMethodOpen] = useState(false);
  const [showAllEvidence, setShowAllEvidence] = useState(false);
  const [isProfileOpen, setIsProfileOpen] = useState(false);

  const insightQuery = useQuery({
    queryKey: insightQueryKeys.detail(insightId),
    queryFn: () => fetchInsight(insightId, companyParam),
    enabled: insightId.length > 0,
    // Запуск анализа платный: не повторять автоматически.
    retry: isPendingEvent ? false : 1,
    staleTime: Infinity,
  });
  const companiesQuery = useQuery({
    queryKey: insightQueryKeys.companies(),
    queryFn: fetchCompanies,
    staleTime: Infinity,
  });
  const loadedInsightId = insightQuery.data?.id ?? "";
  const chatQuery = useQuery({
    queryKey: insightQueryKeys.chat(loadedInsightId),
    queryFn: () => fetchChatHistory(loadedInsightId),
    enabled: !USE_DEMO && loadedInsightId.length > 0 && !loadedInsightId.startsWith(PENDING_PREFIX),
  });
  const askMutation = useMutation({
    mutationFn: (text: string) => askQuestion(loadedInsightId, text, currentRole()),
    onSuccess: (answer) => setMessages((current) => [...current, answer]),
    onError: (error) => setQuestionStatus(error.message),
  });
  const feedbackMutation = useMutation({
    mutationFn: (useful: boolean) => sendFeedback(loadedInsightId, useful),
  });
  // Естественные действия после инсайта (вебинар, вопрос 51): менеджер или аналитик банка.
  const requestMutation = useMutation({
    mutationFn: ({
      kind,
      text,
    }: {
      kind: "manager_callback" | "analyst_question";
      text?: string;
    }) => {
      const current = insightQuery.data;
      if (!current) throw new Error("Анализ не загружен.");
      const lastQuestion = [...messages].reverse().find((item) => item.role === "user")?.text;
      return sendClientRequest(current.companyId, current.id, kind, {
        text: text ?? (kind === "analyst_question" ? question.trim() || lastQuestion : undefined),
        role: currentRole(),
      });
    },
  });
  // Пересчёт сохранённого анализа: агент запускается заново, результат — новый инсайт.
  const reanalyzeMutation = useMutation({
    mutationFn: () => {
      const current = insightQuery.data;
      if (!current?.eventId) throw new Error("Нет события для пересчёта.");
      return reanalyzeInsight(current.companyId, current.eventId);
    },
    onSuccess: (fresh) => navigate(`/insights/${fresh.id}?company=${fresh.companyId}`),
  });

  // После анализа события из ленты переходим на адрес готового инсайта.
  useEffect(() => {
    if (isPendingEvent && insightQuery.data && insightQuery.data.id !== insightId) {
      navigate(`/insights/${insightQuery.data.id}?company=${insightQuery.data.companyId}`, {
        replace: true,
      });
    }
  }, [insightId, insightQuery.data, isPendingEvent, navigate]);

  if (insightQuery.isPending) {
    return (
      <div className="mx-auto max-w-[1195px] space-y-4">
        {isPendingEvent ? (
          <InlineLoadingState label="Агент анализирует событие: собирает данные компании, аналитику банка и проверяет выводы. Обычно 10–60 секунд." />
        ) : null}
        <InsightLoadingState />
      </div>
    );
  }

  if (insightQuery.isError) {
    return (
      <div className="mx-auto max-w-[1195px]">
        <InsightErrorState
          message={
            insightQuery.error instanceof Error
              ? insightQuery.error.message
              : "Не удалось загрузить анализ."
          }
          onRetry={() => void insightQuery.refetch()}
        />
      </div>
    );
  }

  const insight = insightQuery.data;
  const company = companiesQuery.data?.find((item) => item.companyId === insight.companyId);
  const isApiInsight = Boolean(insight.qualityStatus);
  const mechanismSteps =
    insight.mechanismSteps ?? insight.impact.mechanism.split("→").map((stage) => stage.trim());
  const checkItems = insight.impact.nextSteps.length ? insight.impact.nextSteps : DEMO_CHECK_ITEMS;
  const evidenceById = new Map(insight.evidence.map((item) => [item.id, item]));
  const newsEvidence = insight.evidence.find(
    (item) => item.type === "FACT" && item.sourceUrl && !item.sourceId?.startsWith("CL_"),
  );
  const sortedEvidence = [...insight.evidence].sort(
    (first, second) => sourcePriority(first) - sourcePriority(second),
  );
  const evidenceRows = showAllEvidence
    ? sortedEvidence
    : selectEvidencePreview(sortedEvidence, SOURCE_PREVIEW_COUNT);
  const groupedEvidence = SOURCE_GROUPS.map((label) => ({
    label,
    items: evidenceRows.filter((item) => evidenceGroup(item) === label),
  })).filter((group) => group.items.length > 0);
  const evidenceNumberById = new Map(sortedEvidence.map((item, index) => [item.id, index + 1]));
  const contextualAction = getContextualAction(insight);
  const history = [...(chatQuery.data ?? []), ...messages];
  // Чат честно ответил «в данных нет сведений» — предлагаем передать вопрос аналитику.
  const noAnswerYet = Boolean(history.at(-1)?.text?.includes("нет сведений"));

  function toggleCheck(item: string) {
    setCheckedItems((current) =>
      current.includes(item) ? current.filter((value) => value !== item) : [...current, item],
    );
  }

  function submitQuestion() {
    const text = question.trim();
    if (!text || askMutation.isPending) return;
    setMessages((current) => [...current, { role: "user", text }]);
    setQuestion("");
    setQuestionStatus("");
    askMutation.mutate(text);
  }

  function giveFeedback(value: "yes" | "no") {
    setFeedback(value);
    feedbackMutation.mutate(value === "yes");
  }

  return (
    <div className="mx-auto max-w-[1195px] pb-4">
      <nav
        className="flex items-center gap-3 text-[13px] text-[#536071]"
        aria-label="Хлебные крошки"
      >
        <Link
          to={`/insights?company=${encodeURIComponent(insight.companyId)}`}
          className="transition hover:text-[#ef3124]"
        >
          Альфа Сигнал
        </Link>
        <span>/</span>
        <span>Анализ события</span>
      </nav>

      <header className="mt-3">
        <h1 className="text-[34px] font-semibold leading-[1.08] tracking-[-0.042em] text-[#0e1116]">
          {insight.detailTitle ?? insight.title}
        </h1>
        {insight.originalTitle ? (
          <p className="mt-2 text-[14px] text-[#667085]">
            Перевод с английского. Оригинал: «{insight.originalTitle}»
          </p>
        ) : null}
        <div className="mt-2 flex flex-wrap items-center gap-3 text-[14px] text-[#536071]">
          <span>{company?.name ?? formatCompanyName(insight.companyId)}</span>
          <span>·</span>
          <span>{insight.category}</span>
          <span>·</span>
          <span>{dateFormatter.format(new Date(insight.publishedAt))}</span>
          {insight.qualityStatus && insight.qualityStatus !== "verified" ? (
            <span className="text-[12px]">{QUALITY_LABELS[insight.qualityStatus]}</span>
          ) : null}
          {!isApiInsight ? <span className="text-[12px]">Демо-сценарий</span> : null}
          {isApiInsight && insight.analyzedAt ? (
            <span className="text-[12px] text-[#667085]">
              Обновлено {analyzedAtFormatter.format(new Date(insight.analyzedAt))}
            </span>
          ) : null}
          {isApiInsight && insight.eventId ? (
            <button
              type="button"
              onClick={() => reanalyzeMutation.mutate()}
              disabled={reanalyzeMutation.isPending}
              title="Система заново соберёт данные и проверит выводы (до минуты, платный запрос)"
              className="text-[12px] font-medium text-[#171719] underline decoration-[#b8bdc4] underline-offset-4 disabled:text-[#98a2b3] disabled:no-underline"
            >
              {reanalyzeMutation.isPending ? "Пересчитываем… до минуты" : "Пересчитать"}
            </button>
          ) : null}
          {reanalyzeMutation.isError ? (
            <span className="text-[12px] text-[#b42318]">
              {reanalyzeMutation.error instanceof Error
                ? reanalyzeMutation.error.message
                : "Не удалось пересчитать."}
            </span>
          ) : null}
        </div>
      </header>

      <div className="mt-5 grid grid-cols-1 items-start gap-4 min-[1350px]:grid-cols-[minmax(0,760px)_minmax(330px,1fr)]">
        <main className="space-y-3">
          <section className="relative overflow-hidden rounded-[12px] bg-white px-6 py-5 shadow-[0_7px_24px_rgba(24,28,35,0.055)]">
            {/* Метка — по уровню влияния из скоринга: «косвенное» не выдаём за «требует внимания». */}
            {insight.relevanceLevel === "low" ? (
              <span className="inline-flex items-center gap-2 text-[12px] font-semibold text-[#64748b]">
                <AlertCircle className="size-4" aria-hidden="true" /> Косвенное влияние
              </span>
            ) : (
              <span className="inline-flex items-center gap-2 text-[12px] font-semibold text-[#a65b00]">
                <AlertTriangle className="size-4" aria-hidden="true" />{" "}
                {insight.relevanceLevel === "high" ? "Высокая значимость" : "Средняя значимость"}
              </span>
            )}
            <h2 className="mt-3 max-w-[680px] text-[25px] font-semibold leading-[1.15] tracking-[-0.025em]">
              {insight.impact.primaryEffect}
            </h2>
            <p className="mt-2 text-[14px] text-[#4c596a]">
              {insight.cardCaveat ?? "Влияние зависит от условий конкретных договоров компании."}
            </p>
            <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-2 text-[13px] font-medium text-[#334155]">
              {mechanismSteps.map((stage, index) => (
                <span key={`${stage}-${index}`} className="contents">
                  <span>{stage}</span>
                  {index < mechanismSteps.length - 1 ? <FlowArrow /> : null}
                </span>
              ))}
            </div>
            <span className="absolute inset-y-0 right-0 w-1 bg-[#f0b24c]" aria-hidden="true" />
          </section>

          <section className="rounded-[12px] bg-white px-6 py-4 shadow-[0_7px_24px_rgba(24,28,35,0.055)]">
            <div>
              <h2 className="text-[17px] font-semibold">Что произошло</h2>
              <p className="mt-2 text-[14px] leading-5 text-[#3f4a59]">{insight.eventSummary}</p>
              {newsEvidence?.sourceUrl ? (
                <a
                  href={newsEvidence.sourceUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-2 inline-flex items-center gap-2 text-[13px] font-medium text-[#171719] underline decoration-[#b8bdc4] underline-offset-4"
                >
                  <FileText className="size-4" /> Первоисточник:{" "}
                  {newsEvidence.sourceTitle ?? "новость"} <ExternalLink className="size-3.5" />
                </a>
              ) : null}
              {insight.eventSources && insight.eventSources.length > 1 ? (
                <p className="mt-1 text-[12px] text-[#667085]">
                  Источники события ({insight.eventSources.length}):{" "}
                  {insight.eventSources.map((item, index) => (
                    <span key={item.url}>
                      {index ? ", " : ""}
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-[#171719] underline decoration-[#b8bdc4] underline-offset-4"
                      >
                        {item.source}
                      </a>
                    </span>
                  ))}
                </p>
              ) : null}
            </div>
            <div className="mt-4 border-t border-[#e4e7eb] pt-4">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-[17px] font-semibold">Почему это важно вам</h2>
                {isApiInsight ? (
                  <button
                    type="button"
                    onClick={() => setIsMethodOpen((open) => !open)}
                    aria-expanded={isMethodOpen}
                    className="text-[12px] font-medium text-[#171719] underline decoration-[#b8bdc4] underline-offset-4"
                  >
                    {isMethodOpen ? "Скрыть основание" : "Как получен вывод"}
                  </button>
                ) : null}
              </div>
              <ul className="mt-2 space-y-1 text-[14px] leading-5 text-[#3f4a59]">
                {insight.relevanceReasons.map((reason) => (
                  <li key={reason}>• {reason}</li>
                ))}
              </ul>
              {isMethodOpen ? (
                <div className="mt-3 rounded-[9px] bg-[#f2f3f5] px-3 py-2.5">
                  <p className="text-[11px] font-semibold text-[#30343a]">Основание вывода</p>
                  <p className="mt-1 text-[12px] leading-5 text-[#4f5661]">
                    Факты о событии сопоставлены с данными компании и аналитикой банка. Вывод
                    требует проверки по вашим договорам и не гарантирует изменение условий.
                  </p>
                </div>
              ) : null}
              {insight.decisionQuestion ? (
                <div className="mt-3 border-l-[3px] border-[#171719] px-3 py-1">
                  <p className="text-[12px] font-semibold text-[#384252]">Вопрос для решения</p>
                  <p className="mt-1 text-[13px] text-[#4f5a69]">{insight.decisionQuestion}</p>
                </div>
              ) : null}
            </div>
          </section>

          {insight.impact.risks.length || insight.impact.opportunities.length ? (
            <section className="rounded-[12px] bg-white px-6 py-4 shadow-[0_7px_24px_rgba(24,28,35,0.055)]">
              <h2 className="text-[17px] font-semibold">Риски и возможности</h2>
              <ul className="mt-2 space-y-1.5 text-[14px] leading-5 text-[#3f4a59]">
                {insight.impact.risks.map((risk) => (
                  <li key={risk}>
                    <span className="mr-2 rounded bg-[#fff0d4] px-1.5 py-0.5 text-[11px] font-semibold text-[#b76800]">
                      Риск
                    </span>
                    {risk}
                  </li>
                ))}
                {insight.impact.opportunities.map((opportunity) => (
                  <li key={opportunity}>
                    <span className="mr-2 rounded bg-[#e9f7ed] px-1.5 py-0.5 text-[11px] font-semibold text-[#21864a]">
                      Возможность
                    </span>
                    {opportunity}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <section
            id="evidence-bank-example"
            className="rounded-[12px] bg-white px-6 py-4 shadow-[0_7px_24px_rgba(24,28,35,0.055)]"
          >
            <div className="flex items-baseline gap-3">
              <h2 className="text-[17px] font-semibold">Мнение банка</h2>
              <span className="text-[11px] text-[#727780]">
                {!insight.bankView
                  ? "Пример оформления источника"
                  : insight.bankView.status === "found"
                    ? "Аналитика Альфа-Банка"
                    : "Позиция не установлена"}
              </span>
            </div>
            {!insight.bankView ? (
              <>
                <p className="mt-2 text-[14px] leading-5 text-[#3f4a59]">
                  Здесь показан формат отдельного экспертного тезиса с привязкой к материалу банка.
                </p>
                <a
                  href="#evidence-bank"
                  className="mt-3 inline-flex items-center gap-2 text-[13px] font-medium text-[#171719] underline decoration-[#b8bdc4] underline-offset-4"
                >
                  <FileText className="size-4" /> Обзор ключевой ставки · фрагмент [3]
                  <ExternalLink className="size-3.5" />
                </a>
              </>
            ) : insight.bankView.status === "found" ? (
              <>
                <ul className="mt-2 space-y-3">
                  {insight.bankView.claims.map((claim) => (
                    <li key={claim.text}>
                      <p className="text-[14px] leading-5 text-[#3f4a59]">{claim.text}</p>
                      {claim.evidenceIds
                        .map((id) => evidenceById.get(id))
                        .filter(Boolean)
                        .map((source) => (
                          <a
                            key={source!.id}
                            href={source!.sourceUrl}
                            target="_blank"
                            rel="noreferrer"
                            className="mt-1 inline-flex items-center gap-2 text-[13px] font-medium text-[#171719] underline decoration-[#b8bdc4] underline-offset-4"
                          >
                            <FileText className="size-4" /> {source!.sourceTitle} ·{" "}
                            {source!.sourceDate} · стр. {source!.sourcePage}
                            <ExternalLink className="size-3.5" />
                          </a>
                        ))}
                    </li>
                  ))}
                </ul>
                <p className="mt-3 text-[11px] text-[#7a8494]">
                  Мнение аналитиков Альфа-Банка из опубликованных материалов; не является
                  индивидуальной инвестиционной рекомендацией.
                </p>
              </>
            ) : (
              <p className="mt-2 text-[14px] leading-5 text-[#3f4a59]">
                Позиция Альфа-Банка по этому событию не установлена: в подключённых материалах нет
                подтверждённого релевантного тезиса.
              </p>
            )}
          </section>

          <section className="rounded-[12px] bg-white px-6 py-4 shadow-[0_7px_24px_rgba(24,28,35,0.055)]">
            <h2 className="text-[17px] font-semibold">Уточнить анализ</h2>
            {history.length ? (
              <div className="mt-3 space-y-2">
                {history.map((message, index) => (
                  <div
                    key={`${message.role}-${index}`}
                    className={`rounded-md px-3 py-2 text-[13px] leading-5 ${
                      message.role === "user"
                        ? "bg-[#f5f6f8] text-[#303744]"
                        : "bg-[#f5f6f8] text-[#3f4a59]"
                    }`}
                  >
                    {message.claims?.length
                      ? message.claims.map((claim) => (
                          <p key={claim.text} className="mb-1 last:mb-0">
                            <EvidenceBadge type={claim.basis} />{" "}
                            <span className="ml-1">{claim.text}</span>
                          </p>
                        ))
                      : message.text}
                  </div>
                ))}
                {askMutation.isPending ? <InlineLoadingState label="Готовим ответ" /> : null}
              </div>
            ) : null}
            <div className="mt-2 flex flex-wrap gap-2">
              {[
                "Что проверить в договорах?",
                "Какие данные нужны?",
                ...(messages.at(-1)?.followUps ?? []),
              ].map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  onClick={() => setQuestion(prompt)}
                  className="rounded-full border border-[#d7dce2] bg-[#f5f6f8] px-3 py-1.5 text-[12px] text-[#606b7a] transition hover:border-[#aeb6c0]"
                >
                  {prompt}
                </button>
              ))}
            </div>
            <div className="mt-3 flex gap-2">
              <Input
                value={question}
                onChange={(event) => {
                  setQuestion(event.target.value);
                  setQuestionStatus("");
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") submitQuestion();
                }}
                placeholder="Задайте вопрос по этому событию"
                className="h-11 flex-1 rounded-md border-[#cfd5dc]"
              />
              <button
                type="button"
                onClick={submitQuestion}
                disabled={askMutation.isPending}
                aria-label="Отправить вопрос"
                className="grid size-11 place-items-center rounded-md bg-[#f33028] text-white transition hover:bg-[#d92921] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ef3124]/35 disabled:opacity-55"
              >
                <Send className="size-5" aria-hidden="true" />
              </button>
            </div>
            {questionStatus ? (
              <p className="mt-2 text-[11px] text-[#6b7280]">{questionStatus}</p>
            ) : null}
            {isApiInsight ? (
              <div className="mt-3 border-t border-[#eef1f4] pt-3">
                {noAnswerYet ? (
                  <p className="mb-2 text-[12px] text-[#7a5200]">
                    В данных нет ответа на этот вопрос — его можно передать аналитику банка.
                  </p>
                ) : null}
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => requestMutation.mutate({ kind: "analyst_question" })}
                    disabled={requestMutation.isPending}
                    className="h-9 rounded-md border border-[#aeb5be] px-3 text-[13px] font-medium transition hover:bg-[#f5f6f7] disabled:opacity-60"
                  >
                    Задать вопрос аналитику банка
                  </button>
                  <button
                    type="button"
                    onClick={() => requestMutation.mutate({ kind: "manager_callback" })}
                    disabled={requestMutation.isPending}
                    className="h-9 rounded-md border border-[#aeb5be] px-3 text-[13px] font-medium transition hover:bg-[#f5f6f7] disabled:opacity-60"
                  >
                    Связаться с менеджером
                  </button>
                </div>
                {requestMutation.isSuccess ? (
                  <p className="mt-2 text-[12px] text-emerald-700">
                    {requestMutation.data} (демо: заявка сохранена в прототипе)
                  </p>
                ) : null}
                {requestMutation.isError ? (
                  <p className="mt-2 text-[12px] text-[#b42318]">{requestMutation.error.message}</p>
                ) : null}
              </div>
            ) : null}
          </section>
          {isApiInsight ? (
            <details className="px-1 text-[11px] leading-4 text-[#747b86]">
              <summary className="cursor-pointer">О методике анализа</summary>
              <p className="mt-2">
                Факты подтверждаются источниками. Мнение банка вынесено отдельно. Расчётные выводы
                сопровождаются ограничениями и вопросами для проверки.
              </p>
            </details>
          ) : null}
          <Disclaimer />
        </main>

        <aside className="space-y-3">
          <section
            id="company-profile"
            className="rounded-[12px] bg-white p-5 shadow-[0_7px_24px_rgba(24,28,35,0.055)]"
          >
            <h2 className="text-[19px] font-semibold tracking-[-0.02em]">Следующий шаг</h2>
            <h3 className="mt-3 text-[18px] font-semibold">
              {insight.impact.nextSteps[0] ?? "Сверьте условия кредитных договоров"}
            </h3>
            <div className="mt-4 space-y-3">
              {checkItems.map((item) => {
                const isChecked = checkedItems.includes(item);
                return (
                  <label key={item} className="flex cursor-pointer items-center gap-3 text-[14px]">
                    <button
                      type="button"
                      role="checkbox"
                      aria-checked={isChecked}
                      onClick={() => toggleCheck(item)}
                      className={`grid size-6 shrink-0 place-items-center rounded-md border transition ${
                        isChecked
                          ? "border-[#171719] bg-[#171719] text-white"
                          : "border-[#9ca6b4] bg-white"
                      }`}
                    >
                      {isChecked ? <Check className="size-4" /> : null}
                    </button>
                    {item}
                  </label>
                );
              })}
            </div>
            <button
              type="button"
              onClick={() => requestMutation.mutate(contextualAction)}
              disabled={requestMutation.isPending}
              className="mt-5 inline-flex h-11 w-full items-center justify-center rounded-md bg-[#f33028] text-[14px] font-semibold text-white transition hover:bg-[#d92921] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ef3124]/35 disabled:opacity-60"
            >
              {requestMutation.isPending ? "Отправляем…" : contextualAction.label}
            </button>
            {requestMutation.isSuccess ? (
              <p className="mt-2 text-[12px] text-[#237a45]">{requestMutation.data}</p>
            ) : null}
            {requestMutation.isError ? (
              <p className="mt-2 text-[12px] text-[#b42318]">{requestMutation.error.message}</p>
            ) : null}
            <button
              type="button"
              onClick={() => setIsCheckSaved((isSaved) => !isSaved)}
              className="mt-2 h-11 w-full rounded-md border border-[#aeb5be] text-[14px] font-medium transition hover:bg-[#f5f6f7] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ef3124]/30"
            >
              {isCheckSaved ? "Проверка сохранена" : "Сохранить проверку"}
            </button>
          </section>

          <section className="rounded-[12px] bg-white p-5 shadow-[0_7px_24px_rgba(24,28,35,0.055)]">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-[18px] font-semibold">Источники</h2>
              <span className="text-[11px] text-[#727780]">
                {evidenceRows.length} из {sortedEvidence.length}
              </span>
            </div>
            <div className="mt-3 space-y-3">
              {groupedEvidence.map((group) => (
                <div key={group.label}>
                  <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.04em] text-[#727780]">
                    {group.label}
                  </p>
                  <div>
                    {group.items.map((item) => (
                      <EvidenceRow
                        key={item.id}
                        id={
                          item === newsEvidence
                            ? "evidence-event"
                            : item.type === "BANK_ANALYSIS"
                              ? "evidence-bank"
                              : undefined
                        }
                        index={String(evidenceNumberById.get(item.id) ?? "")}
                        title={item.sourceTitle ?? EVIDENCE_TITLES[item.type]}
                        meta={[
                          item.sourceDate,
                          item.sourcePage ? `стр. ${item.sourcePage}` : null,
                          EVIDENCE_TITLES[item.type],
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                        href={item.sourceUrl}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
            {sortedEvidence.length > SOURCE_PREVIEW_COUNT ? (
              <button
                type="button"
                onClick={() => setShowAllEvidence((show) => !show)}
                className="mt-3 text-[12px] font-medium text-[#171719] underline decoration-[#b8bdc4] underline-offset-4"
              >
                {showAllEvidence ? "Свернуть источники" : "Показать все источники"}
              </button>
            ) : null}
          </section>

          <section className="relative overflow-hidden rounded-[12px] bg-white p-5 shadow-[0_7px_24px_rgba(24,28,35,0.055)]">
            <span className="absolute inset-y-0 left-0 w-1 bg-[#f0b24c]" aria-hidden="true" />
            <div className="flex gap-3">
              <span className="grid size-6 shrink-0 place-items-center rounded-full bg-[#e79500] text-white">
                <AlertCircle className="size-4" aria-hidden="true" />
              </span>
              <div>
                <h2 className="text-[14px] font-semibold text-[#9a4300]">Что пока неизвестно</h2>
                <p className="mt-2 text-[12px] leading-[18px] text-[#596372]">
                  {insight.impact.unknowns.length
                    ? `${insight.impact.unknowns.join("; ")}. Без этих данных нельзя точно оценить эффект.`
                    : "Размер задолженности и условия пересмотра ставок. Без них нельзя оценить сумму эффекта."}
                </p>
                {insight.qualityIssues?.length ? (
                  <ul className="mt-2 space-y-1 text-[11px] leading-4 text-[#8a5a00]">
                    {insight.qualityIssues.map((issue) => (
                      <li key={issue}>• {issue}</li>
                    ))}
                  </ul>
                ) : null}
                <button
                  type="button"
                  onClick={() => setIsProfileOpen(true)}
                  disabled={USE_DEMO}
                  className="mt-3 inline-flex items-center gap-2 text-[13px] font-medium text-[#171719] underline decoration-[#b8bdc4] underline-offset-4"
                >
                  Уточнить данные <ArrowRight className="size-4" />
                </button>
              </div>
            </div>
          </section>

          {isApiInsight ? <RoleViewPanel insightId={insight.id} /> : null}
          {isApiInsight && insight.traceId ? <AnalysisTrace insightId={insight.id} /> : null}

          <section className="flex h-[58px] items-center justify-between rounded-[12px] border border-[#e3e7eb] bg-white px-5 shadow-[0_4px_18px_rgba(37,51,68,0.02)]">
            <span className="text-[12px] text-[#647184]">Полезен ли анализ?</span>
            <div className="flex gap-2">
              <FeedbackButton
                active={feedback === "yes"}
                label="Да"
                icon={ThumbsUp}
                onClick={() => giveFeedback("yes")}
              />
              <FeedbackButton
                active={feedback === "no"}
                label="Нет"
                icon={ThumbsDown}
                onClick={() => giveFeedback("no")}
              />
            </div>
          </section>
        </aside>
      </div>
      <CompanyProfilePanel
        companyId={insight.companyId}
        companyName={company?.name ?? formatCompanyName(insight.companyId)}
        open={isProfileOpen}
        onClose={() => setIsProfileOpen(false)}
      />
    </div>
  );
}

function evidenceGroup(item: Evidence): (typeof SOURCE_GROUPS)[number] {
  if (item.type === "BANK_ANALYSIS") return "Аналитика банка";
  if (item.sourceId?.startsWith("CL_")) return "Данные компании";
  if (item.type === "FACT") return "Событие";
  return "Методика";
}

function sourcePriority(item: Evidence): number {
  return SOURCE_GROUPS.indexOf(evidenceGroup(item));
}

function selectEvidencePreview(items: Evidence[], limit: number): Evidence[] {
  const preview: Evidence[] = [];
  for (const group of SOURCE_GROUPS) {
    const first = items.find((item) => evidenceGroup(item) === group);
    if (first && preview.length < limit) preview.push(first);
  }
  for (const item of items) {
    if (preview.length >= limit) break;
    if (!preview.includes(item)) preview.push(item);
  }
  return preview;
}

function getContextualAction(insight: BusinessInsight): {
  kind: "manager_callback" | "analyst_question";
  label: string;
  text: string;
} {
  if (insight.bankView?.status === "not_found") {
    return {
      kind: "analyst_question",
      label: "Уточнить позицию банка",
      text: `Уточните позицию банка по событию «${insight.title}».`,
    };
  }

  const context = [
    insight.category,
    insight.title,
    insight.impact.primaryEffect,
    ...insight.relevanceReasons,
  ]
    .join(" ")
    .toLocaleLowerCase("ru-RU");
  if (/валют|внешн|международ|экспорт|импорт|санкц|расч[её]т/.test(context)) {
    return {
      kind: "manager_callback",
      label: "Обсудить валютные решения",
      text: `Хочу обсудить валютные решения в связи с событием «${insight.title}».`,
    };
  }
  if (/ставк|кредит|лизинг|заимств|финансирован/.test(context)) {
    return {
      kind: "manager_callback",
      label: "Обсудить финансирование",
      text: `Хочу обсудить финансирование в связи с событием «${insight.title}».`,
    };
  }
  return {
    kind: "manager_callback",
    label: "Обсудить влияние с менеджером",
    text: `Хочу обсудить влияние события «${insight.title}» на компанию.`,
  };
}

function FlowArrow() {
  return (
    <span className="relative block h-px w-8 shrink-0 bg-[#7d8794]">
      <ChevronRight className="absolute -right-1.5 -top-[7px] size-3.5 text-[#7d8794]" />
    </span>
  );
}

type EvidenceRowProps = {
  id?: string;
  index: string;
  title: string;
  meta: string;
  href?: string;
};

function EvidenceRow({ id, index, title, meta, href }: EvidenceRowProps) {
  const content = (
    <>
      <span className="grid size-8 shrink-0 place-items-center rounded-md bg-[#eceef1]">
        <FileText className="size-[18px] text-[#536071]" aria-hidden="true" />
      </span>
      <div className="min-w-0">
        <p className="text-[12px] font-semibold">
          [{index}] {title}
        </p>
        <p className="truncate text-[11px] text-[#7b8492]">{meta}</p>
      </div>
      {href ? (
        <ExternalLink className="ml-auto size-4 shrink-0 text-[#637083]" aria-hidden="true" />
      ) : null}
    </>
  );
  const className = "flex items-center gap-3 border-t border-[#e2e4e8] py-2.5";
  return href ? (
    <a
      id={id}
      href={href}
      target="_blank"
      rel="noreferrer"
      className={`${className} hover:bg-[#f7f9fb]`}
    >
      {content}
    </a>
  ) : (
    <div id={id} className={className}>
      {content}
    </div>
  );
}

type FeedbackButtonProps = {
  active: boolean;
  label: string;
  icon: typeof ThumbsUp;
  onClick: () => void;
};

function FeedbackButton({ active, label, icon: Icon, onClick }: FeedbackButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex h-8 min-w-20 items-center justify-center gap-2 rounded-md border text-[12px] transition ${
        active
          ? "border-[#ef3124] bg-[#fff1f0] text-[#d92921]"
          : "border-[#dce1e6] hover:bg-[#f5f6f7]"
      }`}
    >
      <Icon className="size-4" aria-hidden="true" /> {label}
    </button>
  );
}

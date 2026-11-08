import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  ChevronDown,
  CircleHelp,
  FileSearch,
  Info,
  Link2,
  Plus,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { CompanyProfilePanel } from "@/components/insights/CompanyProfilePanel";
import { Disclaimer } from "@/components/insights/Disclaimer";
import { DigestPanel } from "@/components/insights/DigestPanel";
import { BusinessInsightCard } from "@/components/insights/BusinessInsightCard";
import {
  InsightEmptyState,
  InsightErrorState,
  InsightLoadingState,
} from "@/components/insights/InsightStates";
import { Input } from "@/components/ui/input";
import { useCompanySelection } from "@/features/insights/companySelection";
import { analyzeNews, fetchInsightsWorkspace, USE_DEMO } from "@/features/insights/dataSource";
import type { AnalysisContext } from "@/features/insights/model";
import { insightQueryKeys } from "@/features/insights/queries";
import {
  accountRole,
  roleLabel,
  USER_ROLES,
  useUserRole,
  type UserRole,
} from "@/features/insights/role";
import { refreshFeed, setEventHidden } from "@/features/insights/userActions";

const FEED_REFRESH_MS = 5 * 60 * 1000;
const PREANALYSIS_REFRESH_MS = 10 * 1000;

type FeedFilter = "all" | "risk" | "opportunity";

export function InsightsPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { companies, companiesQuery, selectedCompany, selectedCompanyId, selectCompany } =
    useCompanySelection();
  const [selectedFilter, setSelectedFilter] = useState<FeedFilter>("all");
  const [selectedPeriod, setSelectedPeriod] = useState("week");
  const [selectedSort, setSelectedSort] = useState("relevance");
  const [isAnalyzePanelOpen, setIsAnalyzePanelOpen] = useState(false);
  const [isProfileOpen, setIsProfileOpen] = useState(false);
  const [searchValue, setSearchValue] = useState("");
  const [periodReference] = useState(() => Date.now());
  const queryClient = useQueryClient();
  // Сбор идёт на сервере в фоне: перечитываем ленту через несколько секунд.
  const refreshMutation = useMutation({
    mutationFn: refreshFeed,
    onSuccess: () => {
      for (const delay of [3000, 15000]) {
        window.setTimeout(
          () => void queryClient.invalidateQueries({ queryKey: insightQueryKeys.all }),
          delay,
        );
      }
    },
  });
  const hideMutation = useMutation({
    mutationFn: (eventId: string) => setEventHidden(selectedCompanyId, eventId, true),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: insightQueryKeys.all }),
  });
  const [role, setRole] = useUserRole();
  const [analysisUrl, setAnalysisUrl] = useState("");
  const [analysisText, setAnalysisText] = useState("");

  const analysisContext = useMemo<AnalysisContext>(
    () => ({ companyId: selectedCompanyId, groupId: null }),
    [selectedCompanyId],
  );
  const workspaceQuery = useQuery({
    // Роль в ключе: у финдиректора и бухгалтера разный порядок ленты, при смене роли лента перезапрашивается.
    queryKey: [...insightQueryKeys.workspace(analysisContext), role],
    queryFn: () => fetchInsightsWorkspace(analysisContext),
    enabled: selectedCompanyId.length > 0,
    // Бэкенд собирает новости каждые 30 минут, пока сессия активна; лента подтягивает результат.
    // Пока идёт фоновый разбор верхних событий — каждые 10 секунд, иначе раз в 5 минут.
    refetchInterval: (query) =>
      query.state.data?.preanalysisRunning ? PREANALYSIS_REFRESH_MS : FEED_REFRESH_MS,
    refetchOnWindowFocus: true,
  });
  const checklist = workspaceQuery.data?.checklist;

  const analyzeMutation = useMutation({
    mutationFn: () => {
      const url = analysisUrl.trim();
      const text = analysisText.trim();
      return analyzeNews(
        selectedCompanyId,
        url ? { url } : { title: text.split("\n")[0].slice(0, 300), text },
      );
    },
    onSuccess: (insight) => navigate(`/insights/${insight.id}?company=${insight.companyId}`),
  });

  const insights = workspaceQuery.data?.insights ?? [];
  const searchTerm = searchValue.trim().toLocaleLowerCase("ru-RU");
  const periodDays = selectedPeriod === "month" ? 31 : 7;
  const periodCutoff = periodReference - periodDays * 24 * 60 * 60 * 1000;
  const periodInsights = insights
    .filter((insight) => {
      const timestamp = new Date(insight.publishedAt).getTime();
      return Number.isNaN(timestamp) || timestamp >= periodCutoff;
    })
    .filter((insight) => {
      if (!searchTerm) return true;
      return [
        insight.title,
        insight.category,
        insight.cardSummary,
        insight.eventSummary,
        ...insight.relevanceReasons,
      ]
        .join(" ")
        .toLocaleLowerCase("ru-RU")
        .includes(searchTerm);
    });
  const riskCount = periodInsights.filter(
    (insight) => !insight.isPending && (insight.kind === "risk" || insight.kind === "mixed"),
  ).length;
  const opportunityCount = periodInsights.filter(
    (insight) => !insight.isPending && (insight.kind === "opportunity" || insight.kind === "mixed"),
  ).length;
  // Неразобранные события из ленты (isPending) показываются только во вкладке «Все».
  const visibleInsights = periodInsights
    .filter((insight) => {
      if (selectedFilter === "risk") {
        return !insight.isPending && (insight.kind === "risk" || insight.kind === "mixed");
      }
      if (selectedFilter === "opportunity") {
        return !insight.isPending && (insight.kind === "opportunity" || insight.kind === "mixed");
      }
      return true;
    })
    .sort((first, second) => {
      if (selectedSort === "date") {
        return new Date(second.publishedAt).getTime() - new Date(first.publishedAt).getTime();
      }
      const relevanceWeight = { high: 2, medium: 1, low: 0 };
      // Внутри уровня — по баллу 0–100: он учитывает и роль пользователя.
      return (
        relevanceWeight[second.relevanceLevel] - relevanceWeight[first.relevanceLevel] ||
        (second.relevanceScore ?? 0) - (first.relevanceScore ?? 0)
      );
    });

  function handleCompanyChange(companyId: string) {
    setSelectedFilter("all");
    selectCompany(companyId);
  }

  function closeSearch() {
    setSearchValue("");
    const nextParams = new URLSearchParams(searchParams);
    nextParams.delete("search");
    setSearchParams(nextParams, { replace: true });
  }

  function closeProfile() {
    setIsProfileOpen(false);
    const nextParams = new URLSearchParams(searchParams);
    nextParams.delete("profile");
    setSearchParams(nextParams, { replace: true });
  }

  return (
    <div className="mx-auto max-w-[1195px] pb-6">
      <header className="relative pb-5">
        <div className="pr-56">
          <h1 className="text-[42px] font-semibold leading-none tracking-[-0.045em] text-[#0d1015]">
            Альфа Сигнал
          </h1>
          <p className="mt-2 text-[20px] leading-none text-[#4d5666]">
            Что меняется для вашего бизнеса
          </p>
        </div>
        <button
          type="button"
          onClick={() => setIsAnalyzePanelOpen((isOpen) => !isOpen)}
          aria-expanded={isAnalyzePanelOpen}
          className="absolute right-0 top-0 inline-flex h-[42px] items-center gap-2 rounded-md border border-[#ff958d] bg-white px-5 text-[14px] font-semibold text-[#ed2f25] transition hover:bg-[#fff4f3] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ef3124]/35"
        >
          <Plus className="size-5" aria-hidden="true" />
          Разобрать новость
        </button>

        <div className="mt-5 flex items-center gap-3 text-[14px] text-[#374151]">
          <label className="relative inline-flex items-center">
            <select
              value={selectedCompanyId}
              onChange={(event) => handleCompanyChange(event.target.value)}
              className="appearance-none bg-transparent py-1 pr-7 font-medium outline-none"
              aria-label="Выбрать компанию"
            >
              {companies.map((company) => (
                <option key={company.companyId} value={company.companyId}>
                  {company.name}
                </option>
              ))}
            </select>
            <ChevronDown
              className="pointer-events-none absolute right-0 size-4"
              aria-hidden="true"
            />
          </label>
          <span className="size-1 rounded-full bg-[#667085]" />
          {/* Вошёл под учётной записью — роль из неё; без входа — режим просмотра для демонстрации. */}
          {accountRole() ? (
            <span title="Роль задана в учётной записи: от неё зависят порядок ленты и ответы чата">
              {roleLabel(role)}
            </span>
          ) : (
            <label className="relative inline-flex items-center gap-1">
              <span className="text-[#667085]">Режим просмотра: как видит</span>
              <select
                value={role}
                onChange={(event) => setRole(event.target.value as UserRole)}
                className="appearance-none bg-transparent py-1 pr-7 outline-none"
                aria-label="Режим просмотра: лента глазами выбранной роли"
                title="Роль меняет порядок ленты и акценты ответов чата"
              >
                {USER_ROLES.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
              <ChevronDown
                className="pointer-events-none absolute right-0 size-4"
                aria-hidden="true"
              />
            </label>
          )}
          <span className="h-5 w-px bg-[#d6dbe1]" />
          <button
            type="button"
            onClick={() => setIsProfileOpen(true)}
            disabled={USE_DEMO || !selectedCompanyId}
            className="border-b border-[#6b7280] font-medium transition hover:border-[#ef3124] hover:text-[#ef3124] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ef3124]/30 disabled:opacity-50"
          >
            Профиль компании ↗
          </button>
        </div>
      </header>

      {searchParams.get("search") === "open" ? (
        <section className="mb-4 flex items-center gap-3 rounded-[12px] border border-[#e2e6ea] bg-white p-3 shadow-sm">
          <Search className="size-5 shrink-0 text-[#667085]" aria-hidden="true" />
          <Input
            autoFocus
            value={searchValue}
            onChange={(event) => setSearchValue(event.target.value)}
            placeholder="Поиск по событиям и выводам"
            aria-label="Поиск по событиям"
            className="h-10 flex-1 border-0 shadow-none focus-visible:ring-0"
          />
          <button
            type="button"
            onClick={closeSearch}
            aria-label="Закрыть поиск"
            className="grid size-9 place-items-center rounded-md hover:bg-[#f2f3f5]"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        </section>
      ) : null}

      {isAnalyzePanelOpen ? (
        <section className="mb-4 rounded-[12px] border border-[#e2e6ea] bg-white p-4 shadow-sm">
          <div className="flex items-center gap-3">
            <span className="grid size-9 place-items-center rounded-lg bg-[#f0f2f5]">
              <FileSearch className="size-[18px]" aria-hidden="true" />
            </span>
            <div>
              <h2 className="text-[14px] font-semibold">Разобрать новую публикацию</h2>
              <p className="text-[12px] text-[#667085]">Контекст: {selectedCompany?.name}</p>
            </div>
          </div>
          <div className="mt-3 flex gap-2">
            <Input
              type="url"
              value={analysisUrl}
              onChange={(event) => setAnalysisUrl(event.target.value)}
              placeholder="Вставьте ссылку на новость"
              className="h-10 flex-1"
            />
            <button
              type="button"
              disabled={
                USE_DEMO ||
                analyzeMutation.isPending ||
                (!analysisUrl.trim() && !analysisText.trim())
              }
              onClick={() => analyzeMutation.mutate()}
              className="inline-flex h-10 items-center gap-2 rounded-md bg-[#ef3124] px-4 text-[13px] font-semibold text-white transition hover:bg-[#d92a1e] disabled:cursor-not-allowed disabled:opacity-55"
            >
              <Link2 className="size-4" />
              {USE_DEMO
                ? "API не подключено"
                : analyzeMutation.isPending
                  ? "Анализируем…"
                  : "Разобрать"}
            </button>
          </div>
          <textarea
            value={analysisText}
            onChange={(event) => setAnalysisText(event.target.value)}
            placeholder="…или вставьте текст новости: первая строка — заголовок"
            rows={3}
            className="mt-2 w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          />
          {analyzeMutation.isPending ? (
            <p className="mt-2 text-[12px] text-[#667085]">
              Агент собирает данные и проверяет выводы — обычно 10–60 секунд.
            </p>
          ) : null}
          {analyzeMutation.isError ? (
            <p className="mt-2 text-[12px] text-[#c6261b]">{analyzeMutation.error.message}</p>
          ) : null}
        </section>
      ) : null}

      <div className="grid grid-cols-[minmax(0,830px)_minmax(300px,355px)] items-start gap-3">
        <main className="min-w-0">
          {companiesQuery.isError ? (
            <InsightErrorState
              message={companiesQuery.error.message}
              onRetry={() => void companiesQuery.refetch()}
            />
          ) : null}
          {workspaceQuery.isPending && !companiesQuery.isError ? <InsightLoadingState /> : null}
          {workspaceQuery.isError ? (
            <InsightErrorState
              message={
                workspaceQuery.error instanceof Error
                  ? workspaceQuery.error.message
                  : "Не удалось загрузить события."
              }
              onRetry={() => void workspaceQuery.refetch()}
            />
          ) : null}

          {workspaceQuery.isSuccess ? (
            <>
              <section className="flex h-[66px] items-center rounded-[11px] border border-[#e5e8eb] bg-white px-5 shadow-[0_5px_18px_rgba(37,51,68,0.035)]">
                <strong className="whitespace-nowrap text-[22px] tracking-[-0.03em]">
                  {selectedPeriod === "month" ? "За месяц" : "За неделю"}: {periodInsights.length}{" "}
                  {eventCountLabel(periodInsights.length)}
                </strong>
                <span className="mx-5 h-8 w-px bg-[#dfe3e7]" />
                <span className="inline-flex items-center gap-3 text-[17px]">
                  <AlertTriangle className="size-7 fill-[#eca000] text-[#eca000]" />
                  <strong>{riskCount}</strong> риска
                </span>
                <span className="mx-5 h-8 w-px bg-[#dfe3e7]" />
                <span className="inline-flex items-center gap-3 text-[17px]">
                  <BarChart3 className="size-7 text-[#2cb969]" />
                  <strong>{opportunityCount}</strong> возможность
                </span>
                <span className="ml-auto flex items-center gap-2 whitespace-nowrap text-[11px] text-[#7b8492]">
                  {new Date(workspaceQuery.dataUpdatedAt).toLocaleTimeString("ru-RU", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                  {!USE_DEMO ? (
                    <button
                      type="button"
                      onClick={() => refreshMutation.mutate()}
                      disabled={refreshMutation.isPending}
                      title="Обновить ленту: собрать свежие новости и заранее разобрать самое важное"
                      aria-label="Обновить ленту"
                      className="grid size-8 place-items-center rounded-md border border-[#d6dbe1] text-[#354052] hover:bg-[#f5f6f7] disabled:opacity-60"
                    >
                      <RefreshCw
                        className={`size-4 ${refreshMutation.isPending ? "animate-spin" : ""}`}
                        aria-hidden="true"
                      />
                    </button>
                  ) : null}
                </span>
              </section>

              <div className="mt-4 flex h-[43px] items-center gap-3">
                <div className="grid h-full w-[332px] grid-cols-3 rounded-lg border border-[#e0e4e8] bg-white p-1">
                  {(
                    [
                      ["all", "Все"],
                      ["risk", "Риски"],
                      ["opportunity", "Возможности"],
                    ] as const
                  ).map(([value, label]) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setSelectedFilter(value)}
                      className={`rounded-md text-[13px] font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ef3124]/30 ${
                        selectedFilter === value
                          ? "bg-[#f13229] text-white shadow-sm"
                          : "text-[#303744] hover:bg-[#f4f5f6]"
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <FilterSelect
                  value={selectedPeriod}
                  onChange={setSelectedPeriod}
                  options={[
                    { value: "week", label: "За неделю" },
                    { value: "month", label: "За месяц" },
                  ]}
                />
                <FilterSelect
                  value={selectedSort}
                  onChange={setSelectedSort}
                  options={[
                    { value: "relevance", label: "По значимости" },
                    { value: "date", label: "По дате" },
                  ]}
                />
              </div>

              {visibleInsights.length ? (
                <div className="mt-3 space-y-2.5">
                  {visibleInsights.map((insight) => (
                    <BusinessInsightCard
                      key={insight.id}
                      insight={insight}
                      onHide={
                        !USE_DEMO && insight.eventId
                          ? () => hideMutation.mutate(insight.eventId as string)
                          : undefined
                      }
                    />
                  ))}
                </div>
              ) : (
                <div className="mt-3">
                  <InsightEmptyState
                    onReset={() => {
                      setSelectedFilter("all");
                      setSelectedPeriod("month");
                      setSearchValue("");
                    }}
                  />
                </div>
              )}
            </>
          ) : null}
          <div className="mt-3">
            <Disclaimer />
          </div>
        </main>

        <aside id="company-profile" className="space-y-3">
          {!USE_DEMO && selectedCompanyId ? <DigestPanel companyId={selectedCompanyId} /> : null}

          <section className="rounded-[12px] border border-[#e5e8eb] bg-white p-5 shadow-[0_5px_18px_rgba(37,51,68,0.035)]">
            <h2 className="text-[23px] font-semibold tracking-[-0.035em]">Сначала проверьте</h2>
            <div className="mt-4">
              {checklist ? (
                checklist.length ? (
                  checklist.map((item, index) => (
                    <PriorityStep
                      key={item.title}
                      number={String(index + 1)}
                      title={item.title}
                      description={item.description}
                      last={index === checklist.length - 1}
                    />
                  ))
                ) : (
                  <p className="text-[13px] text-[#667085]">
                    Разберите событие из ленты — здесь появятся первые шаги.
                  </p>
                )
              ) : selectedCompanyId === "company-001" ? (
                <>
                  <PriorityStep
                    number="1"
                    title="Даты новых заимствований"
                    description="Проверьте, когда планируете привлекать финансирование и на каких условиях."
                  />
                  <PriorityStep
                    number="2"
                    title="Условия пересмотра ставок"
                    description="Уточните, как изменение ставок повлияет на стоимость заимствований вашей компании."
                    last
                  />
                </>
              ) : (
                <>
                  <PriorityStep
                    number="1"
                    title="Оборот по картам"
                    description="Сверьте фактический оборот с порогами действующей тарифной сетки."
                  />
                  <PriorityStep
                    number="2"
                    title="Текущий тариф эквайринга"
                    description="Уточните комиссию и дату следующего пересмотра условий."
                    last
                  />
                </>
              )}
            </div>
          </section>

          <section className="rounded-[12px] border border-[#e5e8eb] bg-white p-5 shadow-[0_5px_18px_rgba(37,51,68,0.035)]">
            <div className="flex items-center justify-between">
              <h2 className="text-[18px] font-semibold tracking-[-0.02em]">
                Точность персонализации
              </h2>
              <CircleHelp className="size-[18px] text-[#778293]" aria-hidden="true" />
            </div>
            <p className="mt-4 text-[14px] leading-5 text-[#4f5968]">
              {checklist
                ? selectedCompany?.missingData.length
                  ? `Не хватает: ${selectedCompany.missingData.join(", ").toLowerCase()}.`
                  : "Ключевые данные профиля заполнены."
                : selectedCompanyId === "company-001"
                  ? "Не хватает сроков пересмотра ставок и валют контрактов."
                  : "Не хватает месячного оборота и условий тарифа эквайринга."}
            </p>
            <button
              type="button"
              onClick={() => setIsProfileOpen(true)}
              disabled={USE_DEMO || !selectedCompanyId}
              className="mt-5 inline-flex items-center gap-2 text-[14px] font-semibold text-[#ef3124] transition hover:gap-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ef3124]/30 disabled:opacity-50"
            >
              Дополнить профиль <ArrowRight className="size-4" />
            </button>
          </section>

          <section className="rounded-[10px] border border-[#dfe4e9] bg-[#f7f9fb] p-4 text-[#667085]">
            <div className="flex gap-3">
              <Info className="mt-0.5 size-[18px] shrink-0" aria-hidden="true" />
              <div>
                <p className="text-[12px] font-medium text-[#384252]">
                  {USE_DEMO ? "Примеры событий и источников" : "Как собрана лента"}
                </p>
                <p className="mt-2 text-[12px] leading-[18px]">
                  {USE_DEMO
                    ? "В ленте показаны примеры возможных событий, которые могут быть актуальны для вашего бизнеса."
                    : "События отобраны по признакам компании. Подробный анализ с позицией Альфа-Банка запускается по клику на карточку."}
                </p>
              </div>
            </div>
          </section>
        </aside>
      </div>
      <CompanyProfilePanel
        companyId={selectedCompanyId}
        companyName={selectedCompany?.name ?? `Компания ${selectedCompanyId}`}
        open={isProfileOpen || searchParams.get("profile") === "open"}
        onClose={closeProfile}
      />
    </div>
  );
}

type FilterSelectProps = {
  value: string;
  onChange: (value: string) => void;
  options: Array<{ value: string; label: string }>;
};

function FilterSelect({ value, onChange, options }: FilterSelectProps) {
  return (
    <label className="relative block h-full min-w-[155px]">
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-full w-full appearance-none rounded-lg border border-[#e0e4e8] bg-white px-4 pr-10 text-[13px] font-medium text-[#303744] transition hover:bg-[#f7f8f9] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#ef3124]/30"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <ChevronDown
        className="pointer-events-none absolute right-4 top-1/2 size-4 -translate-y-1/2"
        aria-hidden="true"
      />
    </label>
  );
}

type PriorityStepProps = {
  number: string;
  title: string;
  description: string;
  last?: boolean;
};

function PriorityStep({ number, title, description, last = false }: PriorityStepProps) {
  return (
    <div className="flex gap-4">
      <div className="flex w-9 shrink-0 flex-col items-center">
        <span className="grid size-9 place-items-center rounded-full bg-[#f0f2f5] text-[14px] font-semibold">
          {number}
        </span>
        {!last ? <span className="my-1 h-[72px] w-px bg-[#e0e4e8]" /> : null}
      </div>
      <div className={last ? "pb-0" : "pb-4"}>
        <h3 className="pt-1 text-[14px] font-semibold">{title}</h3>
        <p className="mt-2 text-[13px] leading-[19px] text-[#667085]">{description}</p>
      </div>
    </div>
  );
}

function eventCountLabel(count: number): string {
  const mod100 = count % 100;
  const mod10 = count % 10;
  if (mod100 >= 11 && mod100 <= 14) return "событий";
  if (mod10 === 1) return "событие";
  if (mod10 >= 2 && mod10 <= 4) return "события";
  return "событий";
}

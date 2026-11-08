import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  Building2,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Clock3,
  Coins,
  CreditCard,
  FileText,
  Landmark,
  Percent,
  Settings2,
  WalletCards,
} from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { RiskOpportunityCounts } from "@/components/insights/RiskOpportunityCounts";
import { useCompanySelection } from "@/features/insights/companySelection";
import { fetchInsightsWorkspace } from "@/features/insights/dataSource";
import type { BusinessInsight } from "@/features/insights/model";
import { insightQueryKeys } from "@/features/insights/queries";
import { useUserRole } from "@/features/insights/role";

const workItems = [
  { label: "На подпись", value: "1", icon: Clock3, tone: "text-[#4d9dff]" },
  { label: "В работе у банка", value: "7", icon: Settings2, tone: "text-[#4d9dff]" },
  { label: "Отклонено", value: "4", icon: CircleAlert, tone: "text-[#ef3124]" },
];

const rates = [
  { flag: "🇺🇸", code: "USD", buy: "91,20", sell: "92,10" },
  { flag: "🇪🇺", code: "EUR", buy: "99,40", sell: "100,30" },
  { flag: "🇨🇳", code: "CNY", buy: "12,70", sell: "13,10" },
];

const signalTimeFormatter = new Intl.DateTimeFormat("ru-RU", {
  hour: "2-digit",
  minute: "2-digit",
});

export function DashboardPage() {
  const { selectedCompany, selectedCompanyId } = useCompanySelection();
  const [role] = useUserRole();
  const signalContext = {
    companyId: selectedCompanyId,
    groupId: selectedCompany?.groupId ?? null,
  };
  const signalQuery = useQuery({
    queryKey: [...insightQueryKeys.workspace(signalContext), role],
    queryFn: () => fetchInsightsWorkspace(signalContext),
    enabled: Boolean(selectedCompanyId),
    staleTime: 60_000,
  });
  const signals = signalQuery.data?.insights.slice(0, 2) ?? [];
  const signalHref = selectedCompanyId
    ? `/insights?company=${encodeURIComponent(selectedCompanyId)}`
    : "/insights";
  const updatedAt = signalQuery.dataUpdatedAt
    ? signalTimeFormatter.format(new Date(signalQuery.dataUpdatedAt))
    : null;

  return (
    <div className="space-y-5">
      <section className="grid min-h-[318px] overflow-hidden rounded-[14px] bg-[radial-gradient(circle_at_85%_20%,#252a30_0%,#171a1e_45%,#111316_100%)] text-white shadow-[0_10px_30px_rgba(23,28,34,0.12)] lg:grid-cols-[1.25fr_1fr]">
        <div className="flex flex-col p-8">
          <button type="button" className="flex w-fit items-center gap-3 text-[15px] text-white/80">
            <Coins className="size-5" aria-hidden="true" />
            Общий остаток на счетах
            <ChevronDown className="size-4" aria-hidden="true" />
          </button>

          <p className="mt-4 text-[50px] font-semibold leading-none tracking-[0.01em]">
            2 524 550 000,00 ₽
          </p>
          <p className="mt-3 text-[14px] text-white/70">Доступно на счетах ⓘ</p>

          <div className="mt-5 flex items-center gap-14 text-[18px] font-semibold">
            <span className="flex items-center gap-3">
              <span className="grid size-7 place-items-center rounded-full bg-[#ef3124] text-sm">
                🇨🇳
              </span>
              4 000 CNY
            </span>
            <span className="flex items-center gap-3">
              <span className="grid size-7 place-items-center rounded-full bg-[#2ca5d7] text-sm">
                🇰🇿
              </span>
              40 000 KZT
            </span>
          </div>

          <div className="mt-auto flex items-center gap-10 border-t border-white/20 pt-5 text-[14px]">
            <DashboardDarkLink label="Счета" icon={WalletCards} />
            <span className="h-7 w-px bg-white/20" />
            <DashboardDarkLink label="Бизнес-карты" icon={CreditCard} />
            <span className="h-7 w-px bg-white/20" />
            <DashboardDarkLink label="Реквизиты" icon={FileText} />
          </div>
        </div>

        <div className="border-l border-white/15 p-8">
          <h2 className="text-[20px] font-semibold">Дела в работе</h2>
          <div className="mt-4 divide-y divide-white/15">
            {workItems.map(({ label, value, icon: Icon, tone }) => (
              <Link
                key={label}
                to={`/?work=${encodeURIComponent(label)}`}
                className="flex h-[68px] items-center gap-4"
              >
                <span className="grid size-10 place-items-center rounded-full bg-white/7">
                  <Icon className={`size-5 ${tone}`} aria-hidden="true" />
                </span>
                <span className="flex-1 text-[15px]">{label}</span>
                <span className="text-[18px] font-semibold">{value}</span>
                <ChevronRight className="size-4 text-white/75" aria-hidden="true" />
              </Link>
            ))}
          </div>
        </div>
      </section>

      <section className="grid min-h-[144px] overflow-hidden rounded-[14px] bg-white shadow-[0_5px_22px_rgba(25,32,42,0.05)] ring-1 ring-black/[0.035] xl:grid-cols-[300px_1fr_1fr_200px]">
        <Link
          to={signalHref}
          className="flex items-start gap-4 p-6 transition hover:bg-[#fafbfc] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#ef3124]/35"
        >
          <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-[#fff1ef] text-[#ef3124]">
            <SignalBars />
          </span>
          <div className="min-w-0">
            <h2 className="text-[22px] font-semibold tracking-[-0.025em]">Альфа Сигнал</h2>
            <p className="mt-1 text-[14px] text-[#55606e]">
              {signalQuery.isPending
                ? "Загружаем события"
                : signalQuery.isError
                  ? "Не удалось обновить ленту"
                  : `${formatEventCount(signalQuery.data?.insights.length ?? 0)} для компании`}
            </p>
            <p className="mt-1 truncate text-[12px] text-[#5f6977]">
              {selectedCompany?.name ?? "Компания не выбрана"}
            </p>
            <p className="mt-3 text-[12px] text-[#7a8491]">
              {updatedAt ? `Обновлено в ${updatedAt}` : "Данные ещё не загружены"}
            </p>
          </div>
        </Link>

        {[0, 1].map((index) => (
          <DashboardSignal
            key={signals[index]?.id ?? index}
            insight={signals[index]}
            companyId={selectedCompanyId}
            isLoading={signalQuery.isPending}
            hasError={signalQuery.isError}
          />
        ))}

        <div className="flex items-center justify-center border-l border-[#e1e5e9] p-5">
          <Link
            to={signalHref}
            className="inline-flex h-11 w-full items-center justify-center gap-3 rounded-lg bg-[#ef3124] px-4 text-[14px] font-medium text-white transition hover:bg-[#d92a1e]"
          >
            Открыть события
            <ArrowRight className="size-4" aria-hidden="true" />
          </Link>
        </div>
      </section>

      <nav
        className="flex h-[51px] items-end gap-8 border-b border-[#dfe3e8] px-1"
        aria-label="Разделы сводки"
      >
        {[
          { label: "Сводка", active: true },
          { label: "Счета", active: false },
          { label: "Мультибанк", active: false },
          { label: "Металлы", active: false },
        ].map(({ label, active }) => (
          <button
            key={label}
            type="button"
            className={`h-full border-b-[3px] px-1 text-[15px] ${
              active
                ? "border-[#ef3124] font-semibold text-[#11151b]"
                : "border-transparent text-[#596474]"
            }`}
          >
            {label}
          </button>
        ))}
      </nav>

      <section className="grid gap-3 xl:grid-cols-[1.03fr_1fr_1.05fr]">
        <DashboardPanel title="Активные заявки" action="Все заявки">
          <ListRow
            icon={FileText}
            title="Заявка на кредитную линию"
            subtitle="50 000 000 ₽ · 24 октября 2024"
            badge="На рассмотрении"
            badgeTone="amber"
          />
          <ListRow
            icon={FileText}
            title="Открытие валютного счёта"
            subtitle="CNY · 22 октября 2024"
            badge="Исполнено"
            badgeTone="green"
          />
        </DashboardPanel>

        <DashboardPanel title="Курсы валют" action="Все курсы" extra="Демо">
          <div className="grid grid-cols-[1fr_70px_70px] border-b border-[#e5e8eb] pb-2 text-[11px] text-[#6f7986]">
            <span>Валюта</span>
            <span>Покупка</span>
            <span>Продажа</span>
          </div>
          {rates.map((rate) => (
            <div
              key={rate.code}
              className="grid h-[54px] grid-cols-[1fr_70px_70px] items-center border-b border-[#edf0f2] text-[13px]"
            >
              <span className="flex items-center gap-3 font-medium">
                <span className="text-xl">{rate.flag}</span> {rate.code}
              </span>
              <span>{rate.buy}</span>
              <span>{rate.sell}</span>
            </div>
          ))}
          <p className="mt-4 text-[11px] text-[#6f7986]">Курсы носят информационный характер</p>
        </DashboardPanel>

        <DashboardPanel title="Ближайшие платежи" action="Все платежи">
          <ListRow
            icon={Building2}
            title="Поставщикам · сегодня"
            subtitle="3 платежа"
            amount="18 750 000,00 ₽"
          />
          <ListRow
            icon={Percent}
            title="Налоги · 28 октября"
            subtitle="2 платежа"
            amount="7 430 000,00 ₽"
          />
        </DashboardPanel>
      </section>
    </div>
  );
}

function DashboardSignal({
  insight,
  companyId,
  isLoading,
  hasError,
}: {
  insight?: BusinessInsight;
  companyId: string;
  isLoading: boolean;
  hasError: boolean;
}) {
  if (!insight) {
    return (
      <div className="flex flex-col justify-center border-l border-[#e1e5e9] p-5">
        <span className="text-[13px] font-medium text-[#526070]">
          {isLoading
            ? "Загружаем важные события…"
            : hasError
              ? "События временно недоступны"
              : "Других важных событий пока нет"}
        </span>
        <span className="mt-2 text-[12px] leading-5 text-[#7a8491]">
          Лента обновится, когда появятся изменения для компании.
        </span>
      </div>
    );
  }

  return (
    <Link
      to={`/insights/${insight.id}?company=${encodeURIComponent(companyId)}`}
      aria-label={`Открыть анализ: ${insight.title}`}
      className="group border-l border-[#e1e5e9] p-5 transition hover:bg-[#fafbfc] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#ef3124]/35"
    >
      <RiskOpportunityCounts insight={insight} size="compact" />
      <h3 className="mt-3 line-clamp-2 text-[16px] font-semibold leading-5 text-[#171b21] group-hover:text-black">
        {insight.title}
      </h3>
      <p className="mt-2 line-clamp-2 text-[12px] leading-4 text-[#687381]">
        {insight.cardSummary}
      </p>
    </Link>
  );
}

function formatEventCount(count: number): string {
  const lastTwo = count % 100;
  const last = count % 10;
  const noun =
    lastTwo >= 11 && lastTwo <= 14
      ? "событий"
      : last === 1
        ? "событие"
        : last >= 2 && last <= 4
          ? "события"
          : "событий";
  return `${count} ${noun}`;
}

function DashboardDarkLink({ label, icon: Icon }: { label: string; icon: typeof Landmark }) {
  return (
    <Link
      to={`/?section=${encodeURIComponent(label)}`}
      className="flex items-center gap-3 text-white/90"
    >
      <Icon className="size-5" aria-hidden="true" />
      {label}
      <ChevronRight className="size-4 text-white/70" aria-hidden="true" />
    </Link>
  );
}

function DashboardPanel({
  title,
  action,
  extra,
  children,
}: {
  title: string;
  action: string;
  extra?: string;
  children: ReactNode;
}) {
  return (
    <section className="min-h-[342px] rounded-[14px] bg-white p-5 shadow-[0_4px_18px_rgba(25,32,42,0.04)] ring-1 ring-black/[0.035]">
      <div className="mb-4 flex items-center gap-3">
        <h2 className="text-[17px] font-semibold">{title}</h2>
        {extra ? (
          <span className="rounded-md bg-[#f1f3f5] px-2 py-1 text-[11px] text-[#687381]">
            {extra}
          </span>
        ) : null}
        <Link
          to={`/?panel=${encodeURIComponent(title)}`}
          className="ml-auto text-[12px] text-[#596474]"
        >
          {action} <ChevronRight className="inline size-3.5" aria-hidden="true" />
        </Link>
      </div>
      {children}
    </section>
  );
}

function ListRow({
  icon: Icon,
  title,
  subtitle,
  badge,
  badgeTone,
  amount,
}: {
  icon: typeof FileText;
  title: string;
  subtitle: string;
  badge?: string;
  badgeTone?: "amber" | "green";
  amount?: string;
}) {
  return (
    <Link
      to={`/?item=${encodeURIComponent(title)}`}
      className="flex min-h-[76px] items-center gap-3 border-b border-[#edf0f2] py-3"
    >
      <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-[#f1f3f5]">
        <Icon className="size-5" aria-hidden="true" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[13px] font-medium">{title}</span>
        <span className="mt-1 block text-[11px] text-[#687381]">{subtitle}</span>
      </span>
      {badge ? (
        <span
          className={`rounded-full px-2.5 py-1 text-[11px] ${
            badgeTone === "green" ? "bg-[#e3f5e8] text-[#2a7443]" : "bg-[#fff0c8] text-[#a56600]"
          }`}
        >
          {badge}
        </span>
      ) : null}
      {amount ? <span className="text-[13px] font-medium">{amount}</span> : null}
      {amount ? <ChevronRight className="size-4 text-[#677280]" aria-hidden="true" /> : null}
    </Link>
  );
}

function SignalBars() {
  return (
    <span className="flex h-5 items-end gap-[3px]" aria-hidden="true">
      {[10, 18, 14, 21, 12].map((height, index) => (
        <span
          key={`${height}-${index}`}
          className="w-[3px] rounded-full bg-current"
          style={{ height }}
        />
      ))}
    </span>
  );
}

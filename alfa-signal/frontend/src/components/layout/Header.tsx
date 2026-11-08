import { Bell, Building2, ChevronDown, Download, Plus, Search, Upload } from "lucide-react";
import { Link, useLocation } from "react-router";

import { useCompanySelection } from "@/features/insights/companySelection";
import { AccountMenu } from "@/components/layout/AccountMenu";
import { DEMO_AUTH, readSession } from "@/features/insights/session";

export function Header() {
  const location = useLocation();
  const isInsights = location.pathname.startsWith("/insights");

  return (
    <header className="sticky top-0 z-30 border-b border-[#e0e4e8] bg-white/95 backdrop-blur-xl">
      <div className="flex h-[76px] items-center gap-3 px-5 lg:px-6">
        <Link
          to="/"
          className="mr-auto flex items-center gap-2 lg:hidden"
          aria-label="Альфа-Бизнес"
        >
          <span className="grid size-9 place-items-center rounded-lg bg-[#ef3124] font-semibold text-white">
            A
          </span>
          <span className="font-semibold">Альфа-Бизнес</span>
        </Link>

        <span className="mr-auto hidden rounded-md bg-[#eceff2] px-3 py-1.5 text-[12px] text-[#626b78] lg:inline-flex">
          Демонстрационные данные
        </span>

        {isInsights ? <InsightsHeaderActions /> : <DashboardHeaderActions />}
      </div>
    </header>
  );
}

function InsightsHeaderActions() {
  return (
    <>
      <Link
        to="/insights?search=open"
        className="hidden h-10 items-center gap-3 px-3 text-[15px] text-[#364152] transition hover:text-black md:flex"
      >
        <Search className="size-5" aria-hidden="true" />
        Поиск
      </Link>
      <span className="mx-1 hidden h-7 w-px bg-[#dfe3e8] md:block" />
      <NotificationButton />
      <CompanyControl />
      <Avatar initials="ИИ" />
    </>
  );
}

function DashboardHeaderActions() {
  return (
    <>
      <div className="hidden items-center gap-2 xl:flex">
        <HeaderAction to="/?action=download-statement" label="Скачать выписку" icon={Download} />
        <HeaderAction to="/?action=import-payments" label="Импорт платежей" icon={Upload} blue />
        <Link
          to="/?action=create-payment"
          className="ml-2 inline-flex h-11 items-center gap-3 rounded-lg bg-[#ef3124] px-5 text-[14px] font-medium text-white transition hover:bg-[#d92a1e]"
        >
          <Plus className="size-5" aria-hidden="true" />
          Создать платёж
        </Link>
      </div>
      <span className="mx-2 hidden h-7 w-px bg-[#dfe3e8] xl:block" />
      <NotificationButton />
      <CompanyControl />
      <Avatar initials="ИВ" />
    </>
  );
}

function HeaderAction({
  to,
  label,
  icon: Icon,
  blue = false,
}: {
  to: string;
  label: string;
  icon: typeof Download;
  blue?: boolean;
}) {
  return (
    <Link
      to={to}
      className="inline-flex h-10 items-center gap-2.5 px-3 text-[14px] font-medium text-[#18202b] transition hover:text-black"
    >
      <Icon className={`size-5 ${blue ? "text-[#087cff]" : ""}`} aria-hidden="true" />
      {label}
    </Link>
  );
}

function NotificationButton() {
  return (
    <button
      type="button"
      aria-label="Уведомления"
      className="relative grid size-10 place-items-center text-[#27313f]"
    >
      <Bell className="size-5" aria-hidden="true" />
    </button>
  );
}

function CompanyControl() {
  const { companies, companiesQuery, selectedCompany, selectedCompanyId, selectCompany } =
    useCompanySelection();
  const descriptor = selectedCompany
    ? [selectedCompany.industry, selectedCompany.region].filter(Boolean).join(" · ")
    : companiesQuery.isError
      ? "Не удалось загрузить компании"
      : "Загрузка компаний";

  return (
    <label className="relative mx-2 hidden min-w-[260px] items-center gap-3 border-x border-[#e1e4e8] px-4 py-1.5 text-left md:flex">
      <Building2 className="size-5 text-[#27313f]" aria-hidden="true" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[14px] font-semibold">
          {selectedCompany?.name ?? "Компания"}
        </span>
        <span className="block max-w-[190px] truncate text-[12px] text-[#747d8a]">
          {descriptor}
        </span>
      </span>
      <ChevronDown className="size-4 text-[#27313f]" aria-hidden="true" />
      <select
        value={selectedCompanyId}
        onChange={(event) => selectCompany(event.target.value)}
        disabled={!companies.length}
        aria-label="Выбрать компанию"
        className="absolute inset-0 cursor-pointer opacity-0 disabled:cursor-default"
      >
        {companies.map((company) => (
          <option key={company.companyId} value={company.companyId}>
            {company.name} — {company.industry}, {company.region}
          </option>
        ))}
      </select>
    </label>
  );
}

function Avatar({ initials }: { initials: string }) {
  // С входом — меню аккаунта (профиль, данные компании, выход), без входа — ссылка на профиль компании.
  if (DEMO_AUTH && readSession()) return <AccountMenu />;
  return (
    <Link
      to="/?profile=open"
      aria-label="Профиль пользователя"
      className="grid size-11 place-items-center rounded-full bg-[#edf0f3] text-[14px] font-medium text-[#28313e]"
    >
      {initials}
    </Link>
  );
}

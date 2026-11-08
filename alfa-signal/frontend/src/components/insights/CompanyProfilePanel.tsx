import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { DocumentImport } from "@/components/insights/DocumentImport";
import { insightQueryKeys } from "@/features/insights/queries";
import {
  fetchCompanyLinks,
  fetchCompanyProfileFull,
  fetchUserData,
  saveUserData,
  type ApiCompanyProfileFull,
  type CompanyUserData,
} from "@/features/insights/userActions";

const PRODUCT_LABELS: Record<string, string> = {
  rko: "Расчётный счёт",
  gar: "Гарантии",
  loa: "Кредиты",
  lea: "Лизинг",
  dep: "Депозиты",
  zpp: "Зарплатный проект",
};
const MISSING_LABELS: Record<string, string> = {
  "financials.revenue_rub": "выручка",
  "industry.name": "отрасль",
  "location.region": "регион",
  "foreign_trade.country": "страна внешней торговли",
};
const money = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });

function formatRub(value: number | null | undefined): string {
  if (value === null || value === undefined) return "нет данных";
  if (value >= 1e9) return `${money.format(value / 1e9)} млрд ₽`;
  if (value >= 1e6) return `${money.format(value / 1e6)} млн ₽`;
  return `${money.format(value)} ₽`;
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 py-1.5 text-[13px]">
      <dt className="text-[#667085]">{label}</dt>
      <dd className="text-right font-medium text-[#1f2733]">{value}</dd>
    </div>
  );
}

type FormState = {
  floatingDebtMln: string;
  currencies: string;
  countries: string;
  keyInputs: string;
  interests: string;
};

function toForm(data: CompanyUserData | undefined): FormState {
  return {
    floatingDebtMln:
      data?.floating_debt_rub !== undefined && data?.floating_debt_rub !== null
        ? String(data.floating_debt_rub / 1e6)
        : "",
    currencies: (data?.contract_currencies ?? []).join(", "),
    countries: (data?.trade_countries ?? []).join(", "),
    keyInputs: data?.key_inputs ?? "",
    interests: (data?.interests ?? []).join(", "),
  };
}

type CompanyProfilePanelProps = {
  companyId: string;
  companyName: string;
  open: boolean;
  onClose: () => void;
};

export function CompanyProfilePanel({
  companyId,
  companyName,
  open,
  onClose,
}: CompanyProfilePanelProps) {
  const queryClient = useQueryClient();
  const profileQuery = useQuery({
    queryKey: [...insightQueryKeys.all, "profile", companyId],
    queryFn: () => fetchCompanyProfileFull(companyId),
    enabled: open,
  });
  const linksQuery = useQuery({
    queryKey: [...insightQueryKeys.all, "links", companyId],
    queryFn: () => fetchCompanyLinks(companyId),
    enabled: open,
  });
  const userDataQuery = useQuery({
    queryKey: [...insightQueryKeys.all, "user-data", companyId],
    queryFn: () => fetchUserData(companyId),
    enabled: open,
  });
  // Черновик формы; пока пользователь ничего не менял — показываем сохранённые данные.
  const [draft, setForm] = useState<FormState | null>(null);
  const form = draft ?? toForm(userDataQuery.data);

  const saveMutation = useMutation({
    mutationFn: () => {
      const debt = Number(form.floatingDebtMln.replace(",", "."));
      // PUT заменяет сведения целиком: сохраняем и поля, которых нет в форме (из документа).
      const saved = { ...userDataQuery.data };
      delete saved.updated_at;
      return saveUserData(companyId, {
        ...saved,
        floating_debt_rub: form.floatingDebtMln.trim() && debt >= 0 ? debt * 1e6 : undefined,
        interests: form.interests.split(",").filter((item) => item.trim()),
        contract_currencies: form.currencies.split(",").filter((item) => item.trim()),
        trade_countries: form.countries.split(",").filter((item) => item.trim()),
        key_inputs: form.keyInputs.trim() || undefined,
      });
    },
    // Сведения пользователя меняют балл ленты: перечитываем её.
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: insightQueryKeys.all }),
  });

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const profile = profileQuery.data;
  const links = linksQuery.data;
  const products = Object.entries(profile?.products ?? {})
    .filter(([, enabled]) => enabled)
    .map(([key]) => PRODUCT_LABELS[key] ?? key);
  const counterparties = links?.counterparty_industries.industries.slice(0, 5) ?? [];

  const submit = (event: FormEvent) => {
    event.preventDefault();
    saveMutation.mutate();
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={onClose}>
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Профиль компании"
        className="h-full w-full max-w-[480px] overflow-y-auto bg-white p-6 shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-[12px] text-[#667085]">Профиль компании</p>
            <h2 className="text-[22px] font-semibold">{companyName}</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="grid size-9 place-items-center rounded-md hover:bg-[#f0f2f5]"
          >
            <X className="size-5" />
          </button>
        </div>

        {profileQuery.isError ? (
          <p className="mt-4 text-[13px] text-[#b42318]">{String(profileQuery.error.message)}</p>
        ) : null}

        <section className="mt-4">
          <h3 className="text-[14px] font-semibold">По данным банка</h3>
          <dl className="mt-1 divide-y divide-[#eef1f4]">
            <Row label="Отрасль" value={profile?.industry.name ?? "—"} />
            <Row label="Положение в отрасли" value={positionText(profile?.industry_position)} />
            <Row label="Регион" value={profile?.location.region ?? "—"} />
            <Row
              label="Выручка компании за 2025"
              value={formatRub(profile?.financials.revenue_rub)}
            />
            <Row
              label="Выручка группы"
              value={
                links
                  ? `${formatRub(links.group.revenue_rub)}${links.group.revenue_complete ? "" : " (не по всем компаниям)"}`
                  : "—"
              }
            />
            <Row label="Продукты Альфа-Банка" value={products.join(", ") || "—"} />
            <Row
              label="Внешняя торговля (ФТС)"
              value={profile?.risk_indicators.fts_country ?? "нет данных"}
            />
          </dl>
        </section>

        <section className="mt-5">
          <h3 className="text-[14px] font-semibold">Связанные компании</h3>
          {links?.related_companies.length ? (
            <ul className="mt-2 space-y-1.5 text-[13px]">
              {links.related_companies.map((item) => (
                <li key={item.company_id} className="text-[#3f4a59]">
                  <span className="font-medium">{item.company_id}</span> —{" "}
                  {item.okved_name ?? "отрасль не указана"}{" "}
                  <span
                    className={`rounded px-1.5 py-0.5 text-[11px] ${
                      item.certainty === "confirmed"
                        ? "bg-emerald-50 text-emerald-800"
                        : "bg-amber-50 text-amber-800"
                    }`}
                    title={item.basis}
                  >
                    {item.certainty === "confirmed" ? "группа компаний" : "гипотеза: общее физлицо"}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-[13px] text-[#667085]">Связей в данных нет.</p>
          )}
        </section>

        <section className="mt-5">
          <h3 className="text-[14px] font-semibold">Отрасли контрагентов по платежам</h3>
          {counterparties.length ? (
            <>
              <ul className="mt-2 space-y-1 text-[13px] text-[#3f4a59]">
                {counterparties.map((item) => (
                  <li key={`${item.okved_class}-${item.direction}`}>
                    {item.direction === "outgoing" ? "Поставщики" : "Покупатели"}:{" "}
                    {item.example_name ?? `ОКВЭД ${item.okved_class}`} —{" "}
                    {Math.round(item.share * 100)}%
                  </li>
                ))}
              </ul>
              <p className="mt-1 text-[11px] text-[#7a8494]">
                Гипотеза: платёж показывает финансовое взаимодействие, но не его характер.
                {links?.counterparty_industries.unknown_share
                  ? ` Отрасль неизвестна у ${Math.round(links.counterparty_industries.unknown_share * 100)}% суммы.`
                  : ""}
              </p>
            </>
          ) : (
            <p className="mt-1 text-[13px] text-[#667085]">Платёжных данных нет.</p>
          )}
        </section>

        {profile?.data_quality.missing_fields.length ? (
          <p className="mt-5 rounded-md bg-[#fff8ea] px-3 py-2 text-[12px] text-[#7a5200]">
            Не хватает для точного анализа:{" "}
            {profile.data_quality.missing_fields
              .map((field) => MISSING_LABELS[field] ?? field)
              .join(", ")}
          </p>
        ) : null}

        <DocumentImport companyId={companyId} />

        <form
          id="user-data"
          className="mt-5 space-y-3 border-t border-[#e4e7eb] pt-4"
          onSubmit={submit}
        >
          <div>
            <h3 className="text-[14px] font-semibold">Дополнить профиль</h3>
            <p className="mt-1 text-[12px] text-[#667085]">
              Необязательно. Эти сведения учитываются в ленте, анализе и расчётах чата с пометкой
              «со слов пользователя».
            </p>
          </div>
          <label className="block text-[13px]">
            Долг с плавающей ставкой, млн ₽
            <input
              inputMode="decimal"
              value={form.floatingDebtMln}
              onChange={(event) => setForm({ ...form, floatingDebtMln: event.target.value })}
              className="mt-1 h-10 w-full rounded-md border border-[#d6dbe1] px-3"
              placeholder="например, 500"
            />
          </label>
          <label className="block text-[13px]">
            Валюты контрактов
            <input
              value={form.currencies}
              onChange={(event) => setForm({ ...form, currencies: event.target.value })}
              className="mt-1 h-10 w-full rounded-md border border-[#d6dbe1] px-3"
              placeholder="CNY, USD"
            />
          </label>
          <label className="block text-[13px]">
            Страны поставщиков и покупателей
            <input
              value={form.countries}
              onChange={(event) => setForm({ ...form, countries: event.target.value })}
              className="mt-1 h-10 w-full rounded-md border border-[#d6dbe1] px-3"
              placeholder="Китай, Турция"
            />
          </label>
          <label className="block text-[13px]">
            Основные закупки
            <input
              value={form.keyInputs}
              onChange={(event) => setForm({ ...form, keyInputs: event.target.value })}
              className="mt-1 h-10 w-full rounded-md border border-[#d6dbe1] px-3"
              placeholder="металлопрокат, дизельное топливо"
            />
          </label>
          <label className="block text-[13px]">
            Темы, важные компании
            <input
              value={form.interests}
              onChange={(event) => setForm({ ...form, interests: event.target.value })}
              className="mt-1 h-10 w-full rounded-md border border-[#d6dbe1] px-3"
              placeholder="курс юаня, пошлины на металл"
            />
          </label>
          <SavedFromDocuments data={userDataQuery.data} />
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={saveMutation.isPending}
              className="h-10 rounded-md bg-[#ef3124] px-4 text-[14px] font-semibold text-white disabled:opacity-60"
            >
              {saveMutation.isPending ? "Сохраняем…" : "Сохранить"}
            </button>
            {saveMutation.isSuccess ? (
              <span className="text-[12px] text-emerald-700">Сохранено, лента пересчитана</span>
            ) : null}
            {saveMutation.isError ? (
              <span className="text-[12px] text-[#b42318]">{saveMutation.error.message}</span>
            ) : null}
          </div>
        </form>
      </aside>
    </div>
  );
}

function positionText(position: ApiCompanyProfileFull["industry_position"]): string {
  if (!position || position.status !== "ok" || !position.rank || !position.peers) {
    return "недостаточно данных";
  }
  const share = ((position.share_of_sample ?? 0) * 100).toFixed(1).replace(".", ",");
  const group = position.group
    ? `; группа — ${position.group.rank}-е из ${position.group.players}`
    : "";
  return `${position.rank}-е место из ${position.peers} по выручке (${position.tier_label}), доля ${share}% по выборке банка${group}`;
}

const EXTRA_FIELDS: [keyof CompanyUserData, string][] = [
  ["export_share_pct", "Доля экспорта, %"],
  ["revenue_currencies", "Валюты выручки"],
  ["customer_industries", "Отрасли покупателей"],
  ["supplier_industries", "Отрасли поставщиков"],
  ["investment_plans", "Планы инвестиций"],
  ["borrowing_plans", "Планы заимствований"],
  ["covenants", "Ковенанты"],
];

/* Поля, которых нет в форме (обычно из документа), — с отметкой источника. */
function SavedFromDocuments({ data }: { data: CompanyUserData | undefined }) {
  const rows = EXTRA_FIELDS.filter(([key]) => {
    const value = data?.[key];
    return value !== undefined && value !== null && !(Array.isArray(value) && !value.length);
  });
  if (!data || !rows.length) return null;
  return (
    <dl className="divide-y divide-[#eef1f4] rounded-md bg-[#f7f8fa] px-3">
      {rows.map(([key, label]) => {
        const value = data[key];
        const source = data.field_sources?.[key];
        const origin =
          source?.source === "document" ? ` (из документа «${source.document ?? "документ"}»)` : "";
        return (
          <Row
            key={key}
            label={label}
            value={`${Array.isArray(value) ? value.join(", ") : String(value)}${origin}`}
          />
        );
      })}
    </dl>
  );
}

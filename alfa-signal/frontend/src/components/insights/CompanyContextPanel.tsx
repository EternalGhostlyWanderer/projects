import { Building2, ChevronDown, CircleHelp, Gauge, MapPin, Tags } from "lucide-react";

import type { CompanyProfile } from "@/features/insights/model";

type CompanyContextPanelProps = {
  companies: CompanyProfile[];
  company: CompanyProfile;
  onCompanyChange: (companyId: string) => void;
};

export function CompanyContextPanel({
  companies,
  company,
  onCompanyChange,
}: CompanyContextPanelProps) {
  return (
    <aside
      id="company-context"
      className="scroll-mt-24 rounded-3xl bg-white p-5 shadow-[0_4px_18px_rgba(19,20,22,0.045)] ring-1 ring-black/[0.035]"
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.1em] text-[#65666b]">
            Контекст анализа
          </p>
          <h2 className="mt-1 text-lg font-semibold">{company.name}</h2>
        </div>
        <span className="grid size-10 place-items-center rounded-2xl bg-[#f1f2f4]">
          <Building2 className="size-5" aria-hidden="true" />
        </span>
      </div>

      <label className="relative mt-4 block">
        <span className="mb-1.5 block text-xs font-medium text-[#65666b]">
          Выбранная организация
        </span>
        <select
          value={company.companyId}
          onChange={(event) => onCompanyChange(event.target.value)}
          className="h-11 w-full cursor-pointer appearance-none rounded-xl border border-black/10 bg-[#f7f7f8] px-3.5 pr-9 text-sm font-semibold outline-none transition hover:border-black/20 focus:border-black/25 focus:ring-3 focus:ring-[#ef3124]/15"
        >
          {companies.map((item) => (
            <option key={item.companyId} value={item.companyId}>
              {item.name}
            </option>
          ))}
        </select>
        <ChevronDown
          className="pointer-events-none absolute bottom-3.5 right-3.5 size-4 text-[#65666b]"
          aria-hidden="true"
        />
      </label>

      <dl className="mt-4 grid grid-cols-2 gap-3 border-y border-black/7 py-4 text-sm">
        <div>
          <dt className="flex items-center gap-1.5 text-xs text-[#65666b]">
            <Tags className="size-3.5" aria-hidden="true" /> Отрасль
          </dt>
          <dd className="mt-1 font-medium">{company.industry}</dd>
        </div>
        <div>
          <dt className="flex items-center gap-1.5 text-xs text-[#65666b]">
            <MapPin className="size-3.5" aria-hidden="true" /> Регион
          </dt>
          <dd className="mt-1 font-medium">{company.region}</dd>
        </div>
      </dl>

      <div className="mt-4 space-y-4">
        <ContextList title="Признаки бизнеса" items={company.businessFeatures} icon={Tags} />
        <ContextList
          title="Факторы чувствительности"
          items={company.sensitivityFactors}
          icon={Gauge}
        />
        <ContextList
          title="Отсутствующие данные"
          items={company.missingData}
          icon={CircleHelp}
          muted
        />
      </div>

      <p className="mt-4 border-t border-black/7 pt-3 text-xs leading-5 text-[#65666b]">
        {company.profileLabel} · Групповой режим не используется
      </p>
    </aside>
  );
}

type ContextListProps = {
  title: string;
  items: string[];
  icon: typeof Tags;
  muted?: boolean;
};

function ContextList({ title, items, icon: Icon, muted = false }: ContextListProps) {
  return (
    <div>
      <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.07em] text-[#65666b]">
        <Icon className="size-3.5" aria-hidden="true" /> {title}
      </p>
      <ul className="mt-2 flex flex-wrap gap-1.5">
        {items.map((item) => (
          <li
            key={item}
            className={`rounded-lg px-2.5 py-1 text-xs font-medium ${
              muted ? "bg-[#f7f7f8] text-[#5f6065]" : "bg-[#f1f2f4] text-[#3f4045]"
            }`}
          >
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

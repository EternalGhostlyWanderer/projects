import {
  BarChart3,
  CircleHelp,
  CirclePlus,
  Clock3,
  CreditCard,
  FileText,
  Headphones,
  Home,
  Lightbulb,
  ListTree,
  Users,
  WalletCards,
} from "lucide-react";
import type { ComponentType } from "react";
import { NavLink } from "react-router";

import { cn } from "@/lib/utils";

type NavigationItem = {
  label: string;
  icon: ComponentType<{ className?: string }>;
};

const bankingItems: NavigationItem[] = [
  { label: "Заявки", icon: FileText },
  { label: "Новый платёж", icon: CirclePlus },
  { label: "Лента операций", icon: ListTree },
  { label: "Платежи в работе", icon: Clock3 },
  { label: "Выписки", icon: FileText },
  { label: "Счета", icon: WalletCards },
  { label: "Контрагенты", icon: Users },
  { label: "Бизнес-карты", icon: CreditCard },
];

function PlaceholderNavigationItem({ label, icon: Icon }: NavigationItem) {
  return (
    <div className="flex h-[51px] items-center gap-4 px-4 text-[15px] text-[#28313e]" aria-disabled>
      <Icon className="size-5 stroke-[1.8]" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function Sidebar() {
  return (
    <aside className="sticky top-0 hidden h-screen w-[245px] shrink-0 flex-col border-r border-[#dfe3e8] bg-white px-3 py-4 lg:flex">
      <NavLink to="/" className="flex h-[56px] items-center gap-3 px-2" aria-label="Альфа-Бизнес">
        <span className="grid size-[45px] place-items-center rounded-[11px] bg-[#ef3124] text-[25px] font-semibold text-white shadow-[0_5px_14px_rgba(239,49,36,0.2)]">
          A
        </span>
        <span className="text-[20px] font-semibold tracking-[-0.035em]">Альфа-Бизнес</span>
      </NavLink>

      <nav className="mt-5 flex min-h-0 flex-1 flex-col" aria-label="Основная навигация">
        <div className="space-y-1">
          <PrimaryNavLink to="/" end label="Главная" icon={Home} />
          <PrimaryNavLink to="/insights" label="Альфа Сигнал" icon={BarChart3} />
        </div>

        <div className="mx-3 my-4 h-px bg-[#e1e4e8]" />

        <div className="space-y-0.5 overflow-y-auto">
          {bankingItems.map((item) => (
            <PlaceholderNavigationItem key={item.label} {...item} />
          ))}
        </div>

        <div className="mt-auto space-y-0.5 pt-4">
          <BottomItem label="Поддержка" subtitle="Задать вопрос" icon={Headphones} />
          <BottomItem label="Помощь" icon={CircleHelp} />
          <BottomItem label="Предложить идею" icon={Lightbulb} detailOnly />
        </div>
      </nav>
    </aside>
  );
}

type PrimaryNavLinkProps = NavigationItem & {
  to: string;
  end?: boolean;
};

function PrimaryNavLink({ to, end, label, icon: Icon }: PrimaryNavLinkProps) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cn(
          "relative flex h-[47px] items-center gap-4 rounded-lg px-4 text-[15px] transition",
          isActive
            ? "bg-[#eef0f2] font-semibold text-[#11151b] before:absolute before:-left-1 before:h-[39px] before:w-1 before:rounded-r-full before:bg-[#ef3124]"
            : "text-[#28313e] hover:bg-[#f5f6f7]",
        )
      }
    >
      <Icon className="size-5 stroke-[2]" aria-hidden="true" />
      {label}
    </NavLink>
  );
}

type BottomItemProps = NavigationItem & {
  subtitle?: string;
  detailOnly?: boolean;
};

function BottomItem({ label, subtitle, icon: Icon, detailOnly }: BottomItemProps) {
  return (
    <div
      className={cn(
        "flex min-h-[48px] items-center gap-4 px-4 text-[14px] text-[#28313e]",
        detailOnly && "hidden xl:flex",
      )}
    >
      <Icon className="size-5 stroke-[1.8]" aria-hidden="true" />
      <span>
        <span className="block">{label}</span>
        {subtitle ? <span className="block text-[12px] text-[#7b8491]">{subtitle}</span> : null}
      </span>
    </div>
  );
}

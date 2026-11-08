import { useEffect, useState } from "react";

import { DEMO_AUTH, readSession } from "@/features/insights/session";

/* Роль пользователя (вебинар, вопрос 31): ответы чата расставляют акценты под её задачи. */
export const USER_ROLES = [
  { id: "owner", label: "Собственник" },
  { id: "ceo", label: "Генеральный директор" },
  { id: "cfo", label: "Финансовый директор" },
  { id: "accountant", label: "Главный бухгалтер" },
  { id: "treasury", label: "Казначейство" },
  { id: "other", label: "Другая роль" },
] as const;

export type UserRole = (typeof USER_ROLES)[number]["id"];

const STORAGE_KEY = "alfa-signal-role";
const DEFAULT_ROLE: UserRole = "cfo";
/* Смена роли в одном месте (переключатель ленты) обновляет и шапку. */
const ROLE_EVENT = "alfa-signal-role-change";

export function roleLabel(role: string): string {
  return USER_ROLES.find((item) => item.id === role)?.label ?? role;
}

export function storeRole(role: string): void {
  if (!isRole(role)) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, role);
  } catch {
    /* без localStorage роль живёт до перезагрузки страницы */
  }
  window.dispatchEvent(new Event(ROLE_EVENT));
}

function isRole(value: unknown): value is UserRole {
  return USER_ROLES.some((role) => role.id === value);
}

/* Роль из учётной записи: в настоящем банке она задаётся при входе, сотрудник её не меняет. */
export function accountRole(): UserRole | null {
  const role = DEMO_AUTH ? readSession()?.role : undefined;
  return isRole(role) ? role : null;
}

function readRole(): UserRole {
  const fromAccount = accountRole();
  if (fromAccount) return fromAccount;
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return isRole(value) ? value : DEFAULT_ROLE;
  } catch {
    return DEFAULT_ROLE;
  }
}

export function useUserRole(): [UserRole, (role: UserRole) => void] {
  const [role, setRole] = useState<UserRole>(readRole);
  useEffect(() => {
    const sync = () => setRole(readRole());
    window.addEventListener(ROLE_EVENT, sync);
    return () => window.removeEventListener(ROLE_EVENT, sync);
  }, []);
  return [role, storeRole];
}

export function currentRole(): UserRole {
  return readRole();
}

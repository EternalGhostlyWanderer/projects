/* Вход (вебинар, вопрос 63): включается VITE_DEMO_AUTH=1. Локально — демо-учётки из README,
   на сервере (AUTH_STRICT=1) — пользователи из AUTH_USERS. */
export const DEMO_AUTH = import.meta.env.VITE_DEMO_AUTH === "1";
/* 0 — не подсказывать на экране входа, что учётные данные в README (внешний сервер). */
export const LOGIN_HINT = import.meta.env.VITE_LOGIN_HINT !== "0";

export interface DemoSession {
  login: string;
  /* Компании пользователя; пусто — все из VITE_COMPANY_IDS. */
  companies: string[];
  /* Пользователь и роль из /auth/login: передаются в X-User-Id и X-User-Role. */
  user_id?: string;
  name?: string;
  role?: string;
  access_token?: string;
  expires_at?: number;
  /* Когда продлить токен (секунды): половина срока; см. renewSessionIfDue в api.ts. */
  refresh_after?: number;
}

const STORAGE_KEY = "alfa-signal-session";

const EXPIRED_KEY = "alfa-signal-session-expired";

export function readSession(): DemoSession | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const session = raw ? (JSON.parse(raw) as DemoSession) : null;
    // Срок токена (expires_at, секунды) продлевается, пока сайт открыт; просроченную сессию не используем.
    if (session?.expires_at && session.expires_at * 1000 <= Date.now()) {
      window.localStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return session;
  } catch {
    return null;
  }
}

/* Сервер отклонил токен: выйти и показать экран входа с пояснением. */
export function expireSession(): void {
  if (!DEMO_AUTH) return;
  saveSession(null);
  try {
    window.sessionStorage.setItem(EXPIRED_KEY, "1");
  } catch {
    /* пояснение необязательно */
  }
  window.location.assign("/");
}

let expiredNotice: boolean | null = null;

/* Пояснение «сессия истекла» — один раз за загрузку страницы (повторный вызов вернёт то же). */
export function takeExpiredNotice(): boolean {
  if (expiredNotice === null) {
    try {
      expiredNotice = window.sessionStorage.getItem(EXPIRED_KEY) === "1";
      window.sessionStorage.removeItem(EXPIRED_KEY);
    } catch {
      expiredNotice = false;
    }
  }
  return expiredNotice;
}

export function saveSession(session: DemoSession | null): void {
  try {
    if (session) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* без localStorage вход действует до перезагрузки страницы */
  }
}

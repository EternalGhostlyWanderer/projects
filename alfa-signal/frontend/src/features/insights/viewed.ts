/* Просмотренные карточки ленты — как прочитанные сообщения. Хранится только в браузере пользователя. */
const STORAGE_KEY = "alfa-signal:viewed-insights";
const MAX_ITEMS = 500;

function read(): string[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed)
      ? parsed.filter((item): item is string => typeof item === "string")
      : [];
  } catch {
    return [];
  }
}

export function isViewed(id: string): boolean {
  return read().includes(id);
}

export function markViewed(id: string): void {
  try {
    const items = read().filter((item) => item !== id);
    items.push(id);
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(-MAX_ITEMS)));
  } catch {
    /* хранилище недоступно (приватный режим) — карточка просто останется непрочитанной */
  }
}

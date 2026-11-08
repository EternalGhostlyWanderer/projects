import { Building2, ChevronDown, KeyRound, LogOut, UserRound, X } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";

import { Field, FormError, INPUT } from "@/components/account/FormControls";
import { updateProfile } from "@/features/insights/account";
import { roleLabel, USER_ROLES, useUserRole } from "@/features/insights/role";
import { readSession, saveSession } from "@/features/insights/session";

/* Кнопка аккаунта в шапке: опускается плашка с именем и ролью, оттуда — профиль, данные компании, выход. */
export function AccountMenu() {
  const [session, setSession] = useState(readSession);
  const [role] = useUserRole();
  const [open, setOpen] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (!open) return;
    const onClick = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onClick);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!session) return null;
  const name = session.name || session.login;

  return (
    <div ref={menuRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-haspopup="menu"
        className="flex items-center gap-3 rounded-lg px-1 py-1 transition hover:bg-[#f3f5f7]"
      >
        <span className="hidden max-w-[180px] text-right md:block">
          <span className="block truncate whitespace-nowrap text-[14px] font-semibold">{name}</span>
          <span className="block truncate whitespace-nowrap text-[12px] text-[#747d8a]">
            {roleLabel(role)}
          </span>
        </span>
        <span className="grid size-11 place-items-center rounded-full bg-[#edf0f3] text-[14px] font-medium uppercase text-[#28313e]">
          {initials(name)}
        </span>
        <ChevronDown
          className={`size-4 text-[#18202b] transition ${open ? "rotate-180" : ""}`}
          aria-hidden="true"
        />
      </button>

      {open ? (
        <div
          role="menu"
          className="absolute right-0 top-[calc(100%+8px)] z-40 w-[290px] rounded-xl border border-[#e3e7eb] bg-white p-2 shadow-[0_12px_32px_rgba(37,51,68,0.14)]"
        >
          <div className="px-3 py-2.5">
            <p className="truncate text-[15px] font-semibold text-[#111318]">{name}</p>
            <p className="mt-0.5 truncate text-[12px] text-[#687386]">
              {session.login} · {roleLabel(role)}
            </p>
          </div>
          <div className="my-1 h-px bg-[#eceff2]" />
          <MenuItem
            icon={UserRound}
            label="Профиль и пароль"
            onClick={() => {
              setOpen(false);
              setDialogOpen(true);
            }}
          />
          <MenuItem
            icon={Building2}
            label="Данные компании"
            onClick={() => {
              setOpen(false);
              navigate("/insights?profile=open");
            }}
          />
          <div className="my-1 h-px bg-[#eceff2]" />
          <MenuItem
            icon={LogOut}
            label="Выйти"
            danger
            onClick={() => {
              saveSession(null);
              window.location.assign("/");
            }}
          />
        </div>
      ) : null}

      {dialogOpen ? (
        <ProfileDialog
          onClose={() => setDialogOpen(false)}
          onSaved={() => setSession(readSession())}
        />
      ) : null}
    </div>
  );
}

function MenuItem({
  icon: Icon,
  label,
  onClick,
  danger = false,
}: {
  icon: typeof UserRound;
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-[14px] transition hover:bg-[#f3f5f7] ${
        danger ? "text-[#c4281c]" : "text-[#27313f]"
      }`}
    >
      <Icon className="size-[18px]" aria-hidden="true" />
      {label}
    </button>
  );
}

function ProfileDialog({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const session = readSession();
  const [role] = useUserRole();
  const [form, setForm] = useState({
    name: session?.name || session?.login || "",
    role: session?.role || role,
    current: "",
    next: "",
    repeat: "",
  });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const set = (key: keyof typeof form) => (value: string) => {
    setSaved(false);
    setForm((current) => ({ ...current, [key]: value }));
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (form.next && form.next !== form.repeat) {
      setError("Новые пароли не совпадают");
      return;
    }
    setPending(true);
    setError("");
    try {
      await updateProfile({
        name: form.name.trim(),
        role: form.role,
        ...(form.next ? { current_password: form.current, new_password: form.next } : {}),
      });
      onSaved();
      setSaved(true);
      setForm((current) => ({ ...current, current: "", next: "", repeat: "" }));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Не удалось сохранить");
    } finally {
      setPending(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-[#0e1116]/40 px-4 py-6"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <form
        onSubmit={submit}
        role="dialog"
        aria-modal="true"
        aria-labelledby="profile-title"
        className="max-h-full w-full max-w-[440px] overflow-y-auto rounded-[14px] bg-white p-6 shadow-[0_20px_50px_rgba(14,17,22,0.25)]"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 id="profile-title" className="text-[20px] font-semibold tracking-[-0.02em]">
              Профиль
            </h2>
            <p className="mt-1 text-[12px] text-[#687386]">Логин: {session?.login}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="grid size-9 place-items-center rounded-md text-[#5b6677] hover:bg-[#f3f5f7]"
          >
            <X className="size-5" aria-hidden="true" />
          </button>
        </div>

        <Field label="Имя">
          <input
            value={form.name}
            onChange={(event) => set("name")(event.target.value)}
            autoComplete="name"
            className={INPUT}
          />
        </Field>
        <Field label="Роль в компании" hint="Определяет порядок ленты и акценты в разборах">
          <select
            value={form.role}
            onChange={(event) => set("role")(event.target.value)}
            className={`${INPUT} bg-white`}
          >
            {USER_ROLES.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </Field>

        <p className="mt-6 flex items-center gap-2 text-[14px] font-semibold text-[#111318]">
          <KeyRound className="size-4" aria-hidden="true" /> Сменить пароль
        </p>
        <p className="mt-1 text-[11px] text-[#7a8494]">
          Оставьте поля пустыми, если не меняете пароль.
        </p>
        <Field label="Текущий пароль">
          <input
            type="password"
            value={form.current}
            onChange={(event) => set("current")(event.target.value)}
            autoComplete="current-password"
            className={INPUT}
          />
        </Field>
        <Field label="Новый пароль" hint="Не короче 10 символов">
          <input
            type="password"
            value={form.next}
            onChange={(event) => set("next")(event.target.value)}
            autoComplete="new-password"
            className={INPUT}
          />
        </Field>
        <Field label="Повторите новый пароль">
          <input
            type="password"
            value={form.repeat}
            onChange={(event) => set("repeat")(event.target.value)}
            autoComplete="new-password"
            className={INPUT}
          />
        </Field>

        <FormError message={error} />
        {saved ? <p className="mt-3 text-[12px] text-[#21864a]">Изменения сохранены.</p> : null}
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="h-11 rounded-md px-4 text-[14px] font-medium text-[#27313f] hover:bg-[#f3f5f7]"
          >
            Закрыть
          </button>
          <button
            type="submit"
            disabled={pending || !form.name.trim() || Boolean(form.next && !form.current)}
            className="h-11 rounded-md bg-[#ef3124] px-5 text-[14px] font-semibold text-white disabled:opacity-60"
          >
            {pending ? "Сохраняем…" : "Сохранить"}
          </button>
        </div>
      </form>
    </div>
  );
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const letters = parts.length > 1 ? parts[0][0] + parts[1][0] : name.slice(0, 2);
  return letters.toUpperCase();
}

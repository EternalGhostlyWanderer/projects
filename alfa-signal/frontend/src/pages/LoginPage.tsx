import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import { Field, FormError, INPUT } from "@/components/account/FormControls";
import {
  fetchAuthOptions,
  register,
  toSession,
  type AuthOptions,
} from "@/features/insights/account";
import { apiRequest } from "@/features/insights/api";
import { USER_ROLES } from "@/features/insights/role";
import { LOGIN_HINT, takeExpiredNotice, type DemoSession } from "@/features/insights/session";

type Mode = "login" | "register";

export function LoginPage({ onLogin }: { onLogin: (session: DemoSession) => void }) {
  const [mode, setMode] = useState<Mode>("login");
  const [options, setOptions] = useState<AuthOptions | null>(null);
  const [error, setError] = useState(() =>
    takeExpiredNotice() ? "Сессия истекла, войдите снова." : "",
  );

  useEffect(() => {
    // Нет ответа (старый сервер) — просто без вкладки регистрации.
    fetchAuthOptions()
      .then(setOptions)
      .catch(() => setOptions(null));
  }, []);

  const canRegister = Boolean(options?.registration);

  return (
    <main className="grid min-h-screen place-items-center bg-[#f3f4f6] px-4 py-8">
      <div className="w-full max-w-[400px] rounded-[14px] bg-white p-7 shadow-[0_8px_30px_rgba(37,51,68,0.08)]">
        <p className="text-[13px] font-semibold text-[#ef3124]">Альфа-Бизнес</p>
        <h1 className="mt-1 text-[24px] font-semibold tracking-[-0.03em]">
          {mode === "login" ? "Вход в интернет-банк" : "Регистрация"}
        </h1>
        <p className="mt-2 text-[12px] text-[#667085]">
          {mode === "register"
            ? "Учётная запись создаётся сразу, подтверждение администратора не нужно."
            : LOGIN_HINT
              ? "Демонстрационный вход для проверки прототипа «Альфа Сигнал». Учётные данные — в README."
              : canRegister
                ? "Вход в сервис «Альфа Сигнал». Нет учётной записи — зарегистрируйтесь."
                : "Вход в сервис «Альфа Сигнал». Учётную запись выдаёт администратор."}
        </p>

        {canRegister ? (
          <div className="mt-5 grid grid-cols-2 rounded-lg bg-[#f0f2f5] p-1 text-[13px] font-semibold">
            {(["login", "register"] as const).map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => {
                  setMode(item);
                  setError("");
                }}
                className={`h-9 rounded-md transition ${
                  mode === item ? "bg-white text-[#111318] shadow-sm" : "text-[#5b6677]"
                }`}
              >
                {item === "login" ? "Вход" : "Регистрация"}
              </button>
            ))}
          </div>
        ) : null}

        {mode === "login" || !options ? (
          <LoginForm onLogin={onLogin} error={error} setError={setError} />
        ) : (
          <RegisterForm options={options} onLogin={onLogin} error={error} setError={setError} />
        )}
      </div>
    </main>
  );
}

type FormProps = {
  onLogin: (session: DemoSession) => void;
  error: string;
  setError: (message: string) => void;
};

function LoginForm({ onLogin, error, setError }: FormProps) {
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      const session = await apiRequest<DemoSession>("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ login, password }),
      });
      onLogin(toSession(session));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Не удалось войти");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <Field label="Логин">
        <input
          value={login}
          onChange={(event) => setLogin(event.target.value)}
          autoComplete="username"
          className={INPUT}
        />
      </Field>
      <Field label="Пароль">
        <input
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="current-password"
          className={INPUT}
        />
      </Field>
      <FormError message={error} />
      <SubmitButton disabled={pending || !login || !password}>
        {pending ? "Входим…" : "Войти"}
      </SubmitButton>
    </form>
  );
}

function RegisterForm({ options, onLogin, error, setError }: FormProps & { options: AuthOptions }) {
  const [form, setForm] = useState({
    login: "",
    name: "",
    role: "cfo",
    password: "",
    repeat: "",
    code: "",
  });
  const [pending, setPending] = useState(false);
  const roles = options.roles.length ? options.roles : USER_ROLES;
  const set = (key: keyof typeof form) => (value: string) =>
    setForm((current) => ({ ...current, [key]: value }));

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (form.password.length < options.min_password_length) {
      setError(`Пароль должен быть не короче ${options.min_password_length} символов`);
      return;
    }
    if (form.password !== form.repeat) {
      setError("Пароли не совпадают");
      return;
    }
    setPending(true);
    setError("");
    try {
      onLogin(
        await register({
          login: form.login.trim(),
          name: form.name.trim(),
          role: form.role,
          password: form.password,
          code: form.code.trim(),
        }),
      );
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Не удалось зарегистрироваться");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <Field label="Логин" hint="Латинские буквы, цифры, точка, дефис; 3–32 символа">
        <input
          value={form.login}
          onChange={(event) => set("login")(event.target.value)}
          autoComplete="username"
          className={INPUT}
        />
      </Field>
      <Field label="Имя">
        <input
          value={form.name}
          onChange={(event) => set("name")(event.target.value)}
          autoComplete="name"
          className={INPUT}
        />
      </Field>
      <Field label="Роль в компании" hint="Определяет акценты в разборах; можно поменять в профиле">
        <select
          value={form.role}
          onChange={(event) => set("role")(event.target.value)}
          className={`${INPUT} bg-white`}
        >
          {roles.map((role) => (
            <option key={role.id} value={role.id}>
              {role.label}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Пароль" hint={`Не короче ${options.min_password_length} символов`}>
        <input
          type="password"
          value={form.password}
          onChange={(event) => set("password")(event.target.value)}
          autoComplete="new-password"
          className={INPUT}
        />
      </Field>
      <Field label="Повторите пароль">
        <input
          type="password"
          value={form.repeat}
          onChange={(event) => set("repeat")(event.target.value)}
          autoComplete="new-password"
          className={INPUT}
        />
      </Field>
      {options.registration_code_required ? (
        <Field label="Код приглашения" hint="Выдаёт владелец сервиса">
          <input
            value={form.code}
            onChange={(event) => set("code")(event.target.value)}
            className={INPUT}
          />
        </Field>
      ) : null}
      <FormError message={error} />
      <SubmitButton
        disabled={pending || !form.login || !form.name || !form.password || !form.repeat}
      >
        {pending ? "Создаём учётную запись…" : "Зарегистрироваться"}
      </SubmitButton>
    </form>
  );
}

function SubmitButton({ disabled, children }: { disabled: boolean; children: ReactNode }) {
  return (
    <button
      type="submit"
      disabled={disabled}
      className="mt-5 h-11 w-full rounded-md bg-[#ef3124] text-[14px] font-semibold text-white disabled:opacity-60"
    >
      {children}
    </button>
  );
}

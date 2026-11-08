import { apiRequest } from "@/features/insights/api";
import { storeRole } from "@/features/insights/role";
import { readSession, saveSession, type DemoSession } from "@/features/insights/session";

/* Учётная запись: регистрация без администратора и правка профиля (backend app/api/v1/auth.py). */

export interface AuthOptions {
  registration: boolean;
  registration_code_required: boolean;
  min_password_length: number;
  roles: Array<{ id: string; label: string }>;
}

export interface AccountProfile {
  login: string;
  name: string;
  role: string;
  role_label: string;
  companies: string[];
  registered: boolean;
}

export interface RegisterForm {
  login: string;
  password: string;
  name: string;
  role: string;
  code: string;
}

export interface ProfileForm {
  name?: string;
  role?: string;
  current_password?: string;
  new_password?: string;
}

export function fetchAuthOptions(): Promise<AuthOptions> {
  return apiRequest<AuthOptions>("/api/v1/auth/options");
}

export function fetchProfile(): Promise<AccountProfile> {
  return apiRequest<AccountProfile>("/api/v1/auth/me");
}

/* Ответ входа, регистрации и правки профиля — одна и та же сессия. */
export function toSession(response: DemoSession): DemoSession {
  if (response.role) storeRole(response.role);
  return {
    login: response.login,
    companies: response.companies,
    user_id: response.user_id,
    name: response.name,
    role: response.role,
    access_token: response.access_token,
    expires_at: response.expires_at,
    refresh_after: response.refresh_after,
  };
}

export async function register(form: RegisterForm): Promise<DemoSession> {
  const response = await apiRequest<DemoSession>("/api/v1/auth/register", {
    method: "POST",
    body: JSON.stringify(form),
  });
  return toSession(response);
}

/* Новые имя и роль приходят в новом токене: сохраняем сессию, шапка и лента перечитают роль. */
export async function updateProfile(form: ProfileForm): Promise<DemoSession> {
  const response = await apiRequest<DemoSession>("/api/v1/auth/me", {
    method: "PATCH",
    body: JSON.stringify(form),
  });
  const session = { ...readSession(), ...toSession(response) };
  saveSession(session);
  // После сохранения: шапка и лента берут роль из сессии, событие смены роли должно прийти позже.
  if (session.role) storeRole(session.role);
  return session;
}

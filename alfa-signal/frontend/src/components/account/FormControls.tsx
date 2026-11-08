import type { ReactNode } from "react";

/* Поля форм входа, регистрации и профиля — в одном стиле. */
export const INPUT = "mt-1 h-11 w-full rounded-md border border-[#d6dbe1] px-3";

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="mt-3 block text-[13px] first:mt-5">
      {label}
      {children}
      {hint ? <span className="mt-1 block text-[11px] text-[#7a8494]">{hint}</span> : null}
    </label>
  );
}

export function FormError({ message }: { message: string }) {
  return message ? <p className="mt-3 text-[12px] text-[#b42318]">{message}</p> : null;
}

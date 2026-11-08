import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileText } from "lucide-react";
import { useState, type ChangeEvent } from "react";

import { insightQueryKeys } from "@/features/insights/queries";
import {
  applyDocumentFields,
  extractFromDocument,
  type DocumentPreview,
} from "@/features/insights/userActions";

/* «Заполнить из документа»: договор, отчётность или описание компании → поля профиля с цитатами.
   Модель только предлагает; сохраняет пользователь, выбрав нужные поля. Документ не хранится. */
const MAX_BYTES = 8_000_000;

function readAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "");
    reader.onerror = () => reject(new Error("Файл не прочитан"));
    reader.readAsDataURL(file);
  });
}

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "number") return value.toLocaleString("ru-RU");
  return String(value);
}

export function DocumentImport({ companyId }: { companyId: string }) {
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<DocumentPreview | null>(null);
  const [chosen, setChosen] = useState<Set<number>>(new Set());

  const extractMutation = useMutation({
    mutationFn: async () => {
      if (file) {
        if (file.size > MAX_BYTES) throw new Error("Файл больше 8 МБ");
        return extractFromDocument(companyId, {
          filename: file.name,
          file_base64: await readAsBase64(file),
        });
      }
      return extractFromDocument(companyId, { filename: "вставленный текст", text });
    },
    onSuccess: (result) => {
      setPreview(result);
      setChosen(new Set(result.fields.map((_, index) => index)));
    },
  });
  const applyMutation = useMutation({
    mutationFn: () =>
      applyDocumentFields(
        companyId,
        preview?.document ?? "документ",
        (preview?.fields ?? []).filter((_, index) => chosen.has(index)),
      ),
    onSuccess: () => {
      setPreview(null);
      setText("");
      setFile(null);
      // Сведения меняют балл ленты и профиль: перечитываем.
      void queryClient.invalidateQueries({ queryKey: insightQueryKeys.all });
    },
  });

  const toggle = (index: number) => {
    const next = new Set(chosen);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    setChosen(next);
  };

  return (
    <section className="mt-5 space-y-3 border-t border-[#e4e7eb] pt-4">
      <div>
        <h3 className="flex items-center gap-2 text-[14px] font-semibold">
          <FileText className="size-4" aria-hidden="true" /> Заполнить из документа
        </h3>
        <p className="mt-1 text-[12px] text-[#667085]">
          Договор, отчётность или описание компании (TXT, PDF или текст). Модель предложит поля с
          цитатами, сохраните нужные. Документ не хранится; не загружайте персональные данные.
        </p>
      </div>
      <textarea
        value={text}
        onChange={(event) => setText(event.target.value)}
        disabled={Boolean(file)}
        rows={4}
        className="w-full rounded-md border border-[#d6dbe1] px-3 py-2 text-[13px]"
        placeholder="Вставьте текст документа…"
      />
      <input
        type="file"
        accept=".txt,.md,.csv,.pdf"
        onChange={(event: ChangeEvent<HTMLInputElement>) =>
          setFile(event.target.files?.[0] ?? null)
        }
        className="block text-[12px]"
      />
      <button
        type="button"
        onClick={() => extractMutation.mutate()}
        disabled={extractMutation.isPending || (!file && !text.trim())}
        className="h-9 rounded-md border border-[#d6dbe1] px-3 text-[13px] font-medium disabled:opacity-60"
      >
        {extractMutation.isPending ? "Читаем документ…" : "Найти сведения"}
      </button>
      {extractMutation.isError ? (
        <p className="text-[12px] text-[#b42318]">{extractMutation.error.message}</p>
      ) : null}

      {preview ? (
        <div className="space-y-2 rounded-md bg-[#f7f8fa] p-3 text-[13px]">
          <p className="text-[12px] text-[#667085]">
            {preview.document_type || "Документ"}: найдено полей — {preview.fields.length}
            {preview.truncated ? " (документ прочитан не полностью)" : ""}
          </p>
          {preview.fields.length ? (
            <ul className="space-y-2">
              {preview.fields.map((item, index) => (
                <li key={`${item.field}-${index}`}>
                  <label className="flex items-start gap-2">
                    <input
                      type="checkbox"
                      checked={chosen.has(index)}
                      onChange={() => toggle(index)}
                      className="mt-1"
                    />
                    <span>
                      <span className="font-medium">{item.label}:</span> {formatValue(item.value)}
                      <span className="mt-0.5 block text-[12px] text-[#667085] italic">
                        «{item.quote}»
                      </span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          ) : (
            <p>Подходящих сведений в документе не нашлось.</p>
          )}
          {preview.fields.length ? (
            <button
              type="button"
              onClick={() => applyMutation.mutate()}
              disabled={applyMutation.isPending || chosen.size === 0}
              className="h-9 rounded-md bg-[#ef3124] px-3 text-[13px] font-semibold text-white disabled:opacity-60"
            >
              {applyMutation.isPending ? "Сохраняем…" : `Сохранить выбранное (${chosen.size})`}
            </button>
          ) : null}
          {applyMutation.isError ? (
            <p className="text-[12px] text-[#b42318]">{applyMutation.error.message}</p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

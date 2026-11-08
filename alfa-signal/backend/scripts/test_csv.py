"""Inspect CSV metadata without printing company row values."""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def read_sample(path: Path, rows: int) -> tuple[pd.DataFrame, str]:
    errors: list[str] = []
    for encoding in ("utf-8-sig", "cp1251", "utf-8"):
        try:
            frame = pd.read_csv(
                path,
                sep=None,
                engine="python",
                encoding=encoding,
                nrows=rows,
            )
            return frame, encoding
        except pd.errors.EmptyDataError:
            raise RuntimeError("Файл пустой или в нём нет ни одной строки заголовков.")
        except (UnicodeDecodeError, pd.errors.ParserError, csv_error()) as exc:
            errors.append(f"{encoding}: {type(exc).__name__}")
    raise RuntimeError("Не удалось прочитать CSV. Попытки: " + "; ".join(errors))


def csv_error() -> type[Exception]:
    # sep=None использует csv.Sniffer, который бросает csv.Error на неопознанном разделителе.
    import csv

    return csv.Error


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Проверяет структуру CSV без вывода значений строк."
    )
    parser.add_argument("csv_path", help="Путь к CSV, например data/companies.csv")
    parser.add_argument("--rows", type=int, default=1000, help="Размер выборки (по умолчанию 1000)")
    args = parser.parse_args()

    path = Path(args.csv_path).expanduser().resolve()
    if not path.is_file():
        parser.error(f"Файл не найден: {path}")
    if args.rows < 1:
        parser.error("--rows должен быть положительным числом")

    try:
        df, encoding = read_sample(path, args.rows)
    except Exception as exc:
        print(f"Ошибка чтения: {type(exc).__name__}: {exc}")
        return 1

    print(f"Файл: {path.name}")
    print(f"Кодировка: {encoding}")
    print(f"Строк прочитано для проверки: {len(df)} (не обязательно весь файл)")
    print(f"Количество колонок: {len(df.columns)}")

    if df.empty:
        print("Внимание: заголовки есть, но строк данных нет.")
    unnamed = [c for c in df.columns if str(c).startswith("Unnamed:")]
    if unnamed:
        print(f"Внимание: колонки без названия: {len(unnamed)} (возможно, лишний разделитель или неверный заголовок).")
    duplicated = [c for c in df.columns if str(c).rsplit(".", 1)[-1].isdigit() and str(c).rsplit(".", 1)[0] in df.columns]
    if duplicated:
        print(f"Внимание: возможные дубли названий колонок: {len(duplicated)}.")

    print("\nКолонки, типы и пропуски в прочитанной выборке:")
    missing = df.isna().sum()
    for column in df.columns:
        print(
            f"- {column!r}: dtype={df[column].dtype}; "
            f"missing={int(missing[column])}/{len(df)}"
        )

    print("\nЗначения строк не выводились, чтобы не раскрывать данные компаний в терминале.")
    if len(df) == args.rows:
        print("Внимание: выборка ограничена параметром --rows; итоговый объём файла может быть больше.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

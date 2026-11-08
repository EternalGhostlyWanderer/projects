"""Small text helpers shared by fact checks."""
import re

NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)?")


def extract_numbers(text: str) -> set[str]:
    """Numbers in a canonical form: 14,0 → 14, 05 → 5, 3,50 → 3.5."""
    result: set[str] = set()
    for raw in NUMBER_PATTERN.findall(text):
        number = raw.replace(",", ".")
        if "." in number:
            number = number.rstrip("0").rstrip(".")
        result.add(number.lstrip("0") or "0")
    return result


ENGLISH_THOUSANDS = re.compile(r"\b\d{1,3}(?:,\d{3})+\b")


def extract_source_numbers(text: str) -> set[str]:
    """Числа источника с учётом английской записи: «12,500» — это и 12.5, и 12500, и «12 500».

    Русский пересказ англоязычной статьи пишет «12 500» (извлекается как 12 и 500) или «12500»:
    все варианты считаются известными, чтобы перевод не выглядел выдуманной цифрой.
    """
    result = extract_numbers(text)
    for raw in ENGLISH_THOUSANDS.findall(text):
        groups = raw.split(",")
        result.add(str(int("".join(groups))))
        result |= {group.lstrip("0") or "0" for group in groups}
    return result

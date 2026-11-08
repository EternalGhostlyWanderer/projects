"""Fetch a single news article by URL with SSRF protection and plain-text extraction."""
import ipaddress
import re
import socket
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_BYTES = 3_000_000
TIMEOUT = 15
MAX_REDIRECTS = 3
ALLOWED_PORTS = {None, 80, 443}
MIN_PARAGRAPH_CHARS = 40
PAYWALL = re.compile(
    r"доступ\w*\s+(только\s+)?(для\s+)?подписчик|оформите\s+подписк|чтобы\s+(продолжить|прочитать)\s+\w*|"
    r"материал\w*\s+доступ\w*\s+по\s+подписк|полн\w*\s+верси\w*\s+доступн|subscribe\s+to\s+(continue|read)|paywall",
    re.IGNORECASE,
)
# Текст короче — скорее анонс или вырезка, чем статья.
FULL_TEXT_CHARS = 500
HTTP_ERRORS = {
    401: "Сайт требует авторизации — вставьте текст новости вручную",
    402: "Статья доступна только по платной подписке — вставьте текст новости вручную",
    403: "Сайт закрыл доступ (подписка или защита от ботов) — вставьте текст новости вручную",
    404: "Страница не найдена — проверьте ссылку",
    410: "Страница удалена — проверьте ссылку",
    429: "Сайт ограничил частоту запросов — повторите позже или вставьте текст вручную",
    451: "Страница недоступна по юридическим причинам — вставьте текст вручную",
}
SKIPPED_TAGS = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg"}


class ArticleFetchError(ValueError):
    """URL запрещён или статью не удалось получить."""


@dataclass(frozen=True)
class Article:
    url: str
    title: str
    text: str
    source: str
    paywalled: bool = False


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_public_url(url: str) -> str:
    """Allow only http(s) URLs whose host resolves to public addresses."""
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"}:
        raise ArticleFetchError("Разрешены только ссылки http и https")
    if not parts.hostname or parts.username or parts.password:
        raise ArticleFetchError("Некорректный адрес ссылки")
    if parts.port not in ALLOWED_PORTS:
        raise ArticleFetchError("Разрешены только стандартные порты 80 и 443")

    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parts.hostname, None)}
    except socket.gaierror as exc:
        raise ArticleFetchError(f"Не удалось найти сайт {parts.hostname}") from exc

    if not addresses or not all(_is_public(address) for address in addresses):
        raise ArticleFetchError("Ссылка ведёт во внутреннюю сеть — запрос запрещён")
    return url.strip()


class _SafeRedirects(HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        validate_public_url(urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.og_title = ""
        self.paragraphs: list[str] = []
        self.all_text: list[str] = []
        self._skip = 0
        self._in_title = False
        self._paragraph: Optional[list[str]] = None

    def handle_starttag(self, tag, attrs):  # type: ignore[override]
        if tag in SKIPPED_TAGS:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "p" and not self._skip:
            self._paragraph = []
        elif tag == "meta":
            values = dict(attrs)
            if values.get("property") == "og:title" and values.get("content"):
                self.og_title = values["content"]

    def handle_endtag(self, tag):  # type: ignore[override]
        if tag in SKIPPED_TAGS and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag == "p" and self._paragraph is not None:
            text = " ".join("".join(self._paragraph).split())
            if len(text) >= MIN_PARAGRAPH_CHARS:
                self.paragraphs.append(text)
            self._paragraph = None

    def handle_data(self, data):  # type: ignore[override]
        if self._in_title:
            self.title += data
        if self._skip:
            return
        if self._paragraph is not None:
            self._paragraph.append(data)
        self.all_text.append(data)


def parse_article_html(html: str) -> tuple[str, str]:
    parser = _ArticleParser()
    parser.feed(html)
    title = " ".join(unescape(parser.og_title or parser.title).split())
    if parser.paragraphs:
        text = "\n\n".join(parser.paragraphs)
    else:
        text = " ".join(" ".join(parser.all_text).split())
    return title, text


def _decode(body: bytes, content_type: str) -> str:
    charset = None
    match = re.search(r"charset=([\w-]+)", content_type, re.IGNORECASE)
    if match:
        charset = match.group(1)
    else:
        meta = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", body[:4000], re.IGNORECASE)
        if meta:
            charset = meta.group(1).decode("ascii", "ignore")

    for encoding in (charset, "utf-8", "cp1251"):
        if not encoding:
            continue
        try:
            return body.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", errors="replace")


def fetch_article(url: str) -> Article:
    url = validate_public_url(url)
    opener = build_opener(_SafeRedirects())
    request = Request(url, headers={"User-Agent": "Alfa-Signal/0.1"})

    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            content_type = response.headers.get("Content-Type", "")
            if not re.search(r"text/html|text/plain|application/xhtml", content_type):
                raise ArticleFetchError("По ссылке не HTML-страница")
            body = response.read(MAX_BYTES + 1)
            final_url = response.geturl()
    except HTTPError as exc:
        message = HTTP_ERRORS.get(exc.code, f"Сайт ответил ошибкой {exc.code} — вставьте текст новости вручную")
        raise ArticleFetchError(message) from exc
    except (URLError, OSError) as exc:
        if isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError):
            raise ArticleFetchError("Сайт не ответил за 15 секунд — повторите позже или вставьте текст вручную") from exc
        raise ArticleFetchError(f"Не удалось загрузить страницу: {getattr(exc, 'reason', exc)}") from exc

    if len(body) > MAX_BYTES:
        raise ArticleFetchError("Страница слишком большая")

    title, text = parse_article_html(_decode(body, content_type))
    if not title:
        raise ArticleFetchError("Не удалось извлечь статью со страницы — вставьте заголовок и текст вручную")
    # Платный доступ или пустая страница с заголовком: разбор по тому, что есть, с честной пометкой.
    paywalled = bool(PAYWALL.search(text)) and len(text) < FULL_TEXT_CHARS * 4
    if len(text) < MIN_PARAGRAPH_CHARS:
        text = ""
    return Article(
        url=final_url,
        title=title[:500],
        text=text,
        source=urlsplit(final_url).hostname or "web",
        paywalled=paywalled,
    )

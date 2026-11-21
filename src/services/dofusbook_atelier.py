"""Best-effort, read-only import of publicly viewable Dofusbook atelier lists.

No private API, credentials, cookies or account authentication are used.
"""
import re
import unicodedata
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit


_ALLOWED_HOSTS = frozenset({"dofusbook.net", "www.dofusbook.net", "touch.dofusbook.net"})
_BLOCK_TAGS = frozenset({
    "p", "div", "li", "tr", "td", "th", "br", "section", "article",
    "header", "footer", "main", "h1", "h2", "h3", "h4", "span",
})


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fragments: list[str] = []
        self.skip: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript", "svg"):
            self.skip.append(tag)
        if not self.skip and tag in _BLOCK_TAGS:
            self.fragments.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.skip:
            if tag == self.skip[-1]:
                self.skip.pop()
            return
        if tag in _BLOCK_TAGS:
            self.fragments.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.fragments.append(data)

    def text(self) -> str:
        return "".join(self.fragments)


def normalize_item_name(name: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


def _number(value: str) -> int:
    return int(re.sub(r"[^0-9]", "", value))


def parse_atelier_text(text: str, gid_by_name: dict[str, int]) -> dict[int, int]:
    """Recognize Dofusbook 'resource / owned / required' rows and copied lists.

    Supports 'Resource Name' followed by '0 / 12', 'Resource x 12',
    and '12 x Resource'. Unknown names are never guessed.
    """
    lines = [line.strip() for line in text.replace("\xa0", " ").replace("\u202f", " ").splitlines()]
    lines = [line for line in lines if line]
    result: dict[int, int] = {}
    fraction = re.compile(r"^([\d\s]+)\s*/\s*([\d\s]+)$")
    trailing = re.compile(r"^(.+?)\s+[x×]\s*(\d[\d\s]*)$", re.I)
    leading = re.compile(r"^(\d[\d\s]*)\s*[x×]\s+(.+)$", re.I)

    for i, line in enumerate(lines):
        match = fraction.fullmatch(line)
        if match:
            needed = _number(match.group(2))
            if needed <= 0:
                continue
            # A quantity belongs only to the immediately preceding item name.
            # Searching backwards across unknown names can silently assign its
            # quantity to an earlier, recognized resource (e.g. 90 instead of 10).
            if i == 0:
                continue
            gid = gid_by_name.get(normalize_item_name(lines[i - 1]))
            if gid is not None:
                result[gid] = max(result.get(gid, 0), needed)
            continue

        match = trailing.fullmatch(line)
        if match:
            name, raw_count = match.groups()
        else:
            match = leading.fullmatch(line)
            if not match:
                continue
            raw_count, name = match.groups()
        gid = gid_by_name.get(normalize_item_name(name))
        if gid is not None:
            count = _number(raw_count)
            if count > 0:
                result[gid] = max(result.get(gid, 0), count)
    return result


def _validate_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "").rstrip(".").lower() not in _ALLOWED_HOSTS:
        raise ValueError("Utilise un lien HTTPS provenant de dofusbook.net.")
    if parts.username or parts.password:
        raise ValueError("Un lien avec des identifiants n'est pas autorisé.")


def fetch_public_atelier(url: str) -> str:
    """Fetch a public atelier page, with host checks at every redirect."""
    import requests

    current = url.strip()
    for _ in range(4):
        _validate_url(current)
        response = requests.get(
            current,
            headers={"User-Agent": "AstraBot-HDV-CraftPlanner/1.0"},
            timeout=(4, 12),
            allow_redirects=False,
            stream=True,
        )
        try:
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    raise ValueError("Redirection Dofusbook sans destination.")
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").lower()
            if "text/html" not in content_type and "text/plain" not in content_type:
                raise ValueError("Cette page ne renvoie pas une liste HTML consultable.")
            raw = response.raw.read(2_000_001, decode_content=True)
            if len(raw) > 2_000_000:
                raise ValueError("Page Dofusbook trop volumineuse.")
            response.encoding = response.encoding or "utf-8"
            document = raw.decode(response.encoding, errors="replace")
            if "text/plain" in content_type:
                return document
            parser = _VisibleText()
            parser.feed(document)
            return parser.text()
        finally:
            response.close()
    raise ValueError("Trop de redirections Dofusbook.")

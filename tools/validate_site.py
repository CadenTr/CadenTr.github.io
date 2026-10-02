"""Small static-site integrity check for the local portfolio preview."""

from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
PAGES = [
    "index.html",
    "surveying.html",
    "nc-topo.html",
    "independence-park.html",
    "engineering.html",
    "music.html",
]


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.links: list[str] = []
        self.images: list[dict[str, str]] = []
        self.headings: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.append(attributes["id"])
        if tag in {"a", "link"} and attributes.get("href"):
            self.links.append(attributes["href"])
        if tag in {"img", "script", "source"} and attributes.get("src"):
            self.links.append(attributes["src"])
        if tag == "img":
            self.images.append(attributes)
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.headings.append(tag)


def parse_page(path: Path) -> PageParser:
    parser = PageParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


def main() -> None:
    parsed = {page: parse_page(ROOT / page) for page in PAGES}
    errors: list[str] = []

    for page, document in parsed.items():
        duplicates = [item for item, count in Counter(document.ids).items() if count > 1]
        if duplicates:
            errors.append(f"{page}: duplicate ids {duplicates}")
        if document.headings.count("h1") != 1:
            errors.append(f"{page}: expected one h1, found {document.headings.count('h1')}")
        for image in document.images:
            if "alt" not in image:
                errors.append(f"{page}: image missing alt: {image.get('src', '<inline>')}")

        for reference in document.links:
            parts = urlsplit(reference)
            if parts.scheme in {"http", "https", "mailto", "tel", "data"}:
                continue
            local_path = unquote(parts.path)
            target_page = page
            if local_path:
                target = (ROOT / local_path).resolve()
                if not target.exists():
                    errors.append(f"{page}: missing local reference {reference}")
                    continue
                if target.suffix.lower() == ".html":
                    target_page = target.name
            if parts.fragment and target_page in parsed:
                if parts.fragment not in parsed[target_page].ids:
                    errors.append(f"{page}: missing fragment {reference}")

    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Validated {len(PAGES)} pages: local references, fragments, IDs, h1s, and image alt attributes are sound.")


if __name__ == "__main__":
    main()

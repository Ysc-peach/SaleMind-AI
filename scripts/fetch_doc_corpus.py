"""Fetch documentation pages into plain text for a local knowledge corpus.

The corpus itself is not committed: these are third-party documents whose
licence belongs to their publisher. What is committed is the manifest this
script writes — URL, title, size and checksum — so the same corpus can be
rebuilt later without redistributing anyone's text.

Usage:
    python scripts/fetch_doc_corpus.py --out knowledge-seed/tidb-zh URL [URL ...]
"""

import argparse
import hashlib
import html as html_module
import json
import re
import sys
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

SKIP_TAGS = {"script", "style", "nav", "footer", "header", "svg", "form", "noscript"}
BLOCK_TAGS = {
    "p", "div", "section", "article", "main", "li", "tr", "td", "th",
    "h1", "h2", "h3", "h4", "h5", "h6", "pre", "br", "table",
}


class _TextExtractor(HTMLParser):
    """Collect visible text, keeping block boundaries as newlines."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self._skip_depth += 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts).replace("\u00a0", " ")
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.splitlines()]
        kept: list[str] = []
        for line in lines:
            if not line:
                if kept and kept[-1]:
                    kept.append("")
                continue
            # Navigation and cookie banners survive as very short fragments.
            if len(line) <= 3 and not line.isdigit():
                continue
            kept.append(line)
        return "\n".join(kept).strip() + "\n"


def _slug(url: str) -> str:
    path = re.sub(r"^https?://", "", url).rstrip("/")
    return re.sub(r"[^a-zA-Z0-9]+", "-", path).strip("-").lower()[-80:]


def _title(html: str, fallback: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    if not match:
        return fallback
    # Entities such as &#8212; must be decoded, otherwise they end up in the
    # document title the reviewer sees in the Admin.
    return html_module.unescape(re.sub(r"\s+", " ", match.group(1))).strip()


def _trim_to_heading(body: str, title: str) -> str:
    """Drop the navigation block that sits above the article heading.

    Documentation sites repeat the page title in their sidebar, so the heading is
    the *last* line equal to it — everything before that is navigation, not
    evidence the model should be able to cite.
    """

    head = title.split("|")[0].strip()
    if not head:
        return body
    lines = body.splitlines()
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip() == head:
            return "\n".join(lines[index:]).strip() + "\n"
    return body


def _markdown_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip() or fallback
    return fallback


def fetch(url: str, out_dir: Path, timeout: int = 40):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; SalesMind corpus fetch)"})
    with urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")

    if url.endswith(".md"):
        # Documentation sites that serve the source markdown give cleaner text
        # than any HTML extraction, so take it as-is.
        title = _markdown_title(raw, url)
        body = raw.strip() + "\n"
    else:
        extractor = _TextExtractor()
        extractor.feed(raw)
        title = _title(raw, url)
        body = _trim_to_heading(extractor.text(), title)

    name = _slug(url) + ".txt"
    target = out_dir / name
    target.write_text(body, encoding="utf-8")
    return {
        "url": url,
        "file": name,
        "title": title,
        "chars": len(body),
        "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--out", required=True, help="Directory for the text files.")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "sources.json"
    entries = []
    for url in args.urls:
        try:
            entry = fetch(url, out_dir)
        except Exception as error:  # noqa: BLE001 - report and continue
            print(f"FAILED {url}: {type(error).__name__}: {error}", file=sys.stderr)
            continue
        entries.append(entry)
        print(f"{entry['chars']:>7} chars  {entry['file']}  <- {url}")

    if not entries:
        return 1
    manifest = {
        "fetched_on": date.today().isoformat(),
        "note": (
            "Third-party documentation kept for local evaluation only; the text is "
            "not committed and the licence stays with the publisher."
        ),
        "documents": entries,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nwrote {manifest_path} with {len(entries)} document(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

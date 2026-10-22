"""Build English research pages from reviewed copy without changing data or IDs."""

import argparse
import difflib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
PAGES = ("backtest", "market-sentiment", "hk-factor-lab", "navigation")
COPY = json.loads((ROOT / "locales/pages.en.json").read_text(encoding="utf-8"))
CJK = re.compile(r"[\u4e00-\u9fff]")


def english_link(value):
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return value
    if parts.path == "/" or parts.path in {f"/{name}" for name in PAGES}:
        path = "/en" if parts.path == "/" else "/en" + parts.path
        return urlunsplit(("", "", path, parts.query, parts.fragment))
    return value


class EnglishPage(HTMLParser):
    def __init__(self, name):
        super().__init__(convert_charrefs=True)
        self.name = name
        self.output = []
        self.language_link = False

    def translate(self, value):
        text = value.strip()
        if not CJK.search(text):
            return value
        if text not in COPY:
            raise ValueError(f"Unreviewed English copy in {self.name}: {text}")
        return value.replace(text, COPY[text], 1)

    def start(self, tag, attrs, closing):
        attributes = dict(attrs)
        self.language_link = tag == "a" and "language-toggle" in attributes.get("class", "").split()
        rewritten = []
        for key, value in attrs:
            if tag == "html" and key == "lang":
                value = "en"
            elif self.language_link and key == "href":
                value = f"/{self.name}" if self.name != "navigation" else "/"
            elif self.language_link and key in {"lang", "hreflang"}:
                value = "zh-CN"
            elif self.language_link and key == "aria-label":
                value = "Switch to Chinese"
            elif tag == "a" and key == "href":
                value = english_link(value)
            elif value is not None and key in {"content", "aria-label", "title", "placeholder"}:
                value = self.translate(value)
            rewritten.append(key if value is None else f'{key}="{html.escape(value, quote=True)}"')
        self.output.append("<" + tag + (" " + " ".join(rewritten) if rewritten else "") + closing)

    def handle_starttag(self, tag, attrs):
        self.start(tag, attrs, ">")

    def handle_startendtag(self, tag, attrs):
        self.start(tag, attrs, " />")

    def handle_endtag(self, tag):
        self.output.append(f"</{tag}>")
        if tag == "a":
            self.language_link = False

    def handle_data(self, data):
        self.output.append("中文" if self.language_link and data.strip() == "English" else html.escape(self.translate(data), quote=False))

    def handle_entityref(self, name):
        self.output.append(f"&{name};")

    def handle_charref(self, name):
        self.output.append(f"&#{name};")

    def handle_decl(self, decl):
        self.output.append(f"<!{decl}>")

    def handle_comment(self, data):
        self.output.append(f"<!--{data}-->")


def render(name):
    parser = EnglishPage(name)
    parser.feed((PUBLIC / f"{name}.html").read_text(encoding="utf-8"))
    return "".join(parser.output)


def main():
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("--patch", action="store_true")
    options = argument_parser.parse_args()
    changes = []
    for name in PAGES:
        path = PUBLIC / "en" / f"{name}.html"
        expected = render(name)
        actual = path.read_text(encoding="utf-8") if path.exists() else ""
        if actual != expected:
            changes.append((path, actual, expected))
    if options.patch:
        print("*** Begin Patch")
        for path, actual, expected in changes:
            relative = path.relative_to(ROOT).as_posix()
            if not actual:
                print(f"*** Add File: {relative}")
                print("\n".join("+" + line for line in expected.splitlines()))
            else:
                print(f"*** Update File: {relative}")
                difference = list(difflib.unified_diff(actual.splitlines(), expected.splitlines(), lineterm=""))
                print("\n".join("@@" if line.startswith("@@") else line for line in difference[2:]))
        print("*** End Patch")
    elif changes:
        raise SystemExit("English pages need rebuilding: " + ", ".join(str(item[0]) for item in changes))
    else:
        print("Reviewed English pages are in sync")


if __name__ == "__main__":
    main()

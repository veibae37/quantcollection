from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unittest

from build_english_pages import EnglishPage, PAGES, english_link, render

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"


class Document(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.ids = []
        self.links = []
        self.text = []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if "id" in attributes:
            self.ids.append(attributes["id"])
        if tag == "a":
            self.links.append(attributes)

    def handle_data(self, data):
        self.text.append(data)


class SiteLocalizationTests(unittest.TestCase):
    def test_generated_pages_match_reviewed_copy(self):
        for page in PAGES:
            with self.subTest(page=page):
                self.assertEqual(render(page), (PUBLIC / "en" / f"{page}.html").read_text(encoding="utf-8"))

    def test_translations_preserve_ids_and_english_internal_links(self):
        research_paths = {"/", "/backtest", "/market-sentiment", "/hk-factor-lab"}
        for page in PAGES:
            with self.subTest(page=page):
                chinese = Document((PUBLIC / f"{page}.html").read_text(encoding="utf-8"))
                english = Document(render(page))
                self.assertEqual(chinese.ids, english.ids)
                self.assertEqual(len(english.ids), len(set(english.ids)))
                for link in english.links:
                    if "language-toggle" not in link.get("class", ""):
                        self.assertNotIn(link.get("href", "").split("#")[0], research_paths)
                visible = "".join(english.text).replace("中文", "")
                self.assertIsNone(re.search(r"[\u4e00-\u9fff]", visible))

    def test_new_unreviewed_copy_is_rejected(self):
        parser = EnglishPage("test")
        with self.assertRaisesRegex(ValueError, "Unreviewed English copy"):
            parser.feed("<p>尚未审核的新文案</p>")

    def test_route_translation_keeps_query_and_anchor(self):
        self.assertEqual(english_link("/backtest?market=csi1000&topK=50#controls-title"), "/en/backtest?market=csi1000&topK=50#controls-title")
        self.assertEqual(english_link("/#research-engine"), "/en#research-engine")
        self.assertEqual(english_link("/api/live?program=hk_factor"), "/api/live?program=hk_factor")
        self.assertEqual(english_link("https://example.com/backtest"), "https://example.com/backtest")

    def test_all_research_routes_have_english_rewrites(self):
        config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
        routes = {item["source"]: item["destination"] for item in config["rewrites"]}
        for page in PAGES:
            if page != "navigation":
                self.assertEqual(routes.get(f"/en/{page}"), f"/en/{page}.html")


if __name__ == "__main__":
    unittest.main()

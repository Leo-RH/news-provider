"""Offline tests for the scraping engine.

Every page is a small inline fixture served by a fake fetcher, so the suite
never touches the network:  python -m unittest discover tests
"""

import base64
import datetime as dt
import json
import os
import sys
import tempfile
import unittest

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Article import normalize_link  # noqa: E402
from Connector import Connector, ConnectorError  # noqa: E402
from Dates import to_iso  # noqa: E402
from Divisor import Divisor, best_from_srcset, clean_text  # noqa: E402
from Reader import Reader  # noqa: E402

NOW = dt.datetime(2026, 11, 6, 12, 0, tzinfo=dt.timezone.utc)


def make_response(url, body, content_type="text/html; charset=utf-8", status=200):
    response = requests.models.Response()
    response.url = url
    response.status_code = status
    response.headers["Content-Type"] = content_type
    response._content = body if isinstance(body, bytes) else body.encode("utf-8")
    response.encoding = requests.utils.get_encoding_from_headers(response.headers)
    return response


class FakeFetcher:
    """Serves canned responses; unknown URLs fail like a dead server."""

    def __init__(self, pages):
        self.pages = pages
        self.session = requests.Session()
        self.requested = []

    def get(self, url, headers=None, timeout=15):
        self.requested.append(url)
        if url not in self.pages:
            raise requests.ConnectionError(f"no route to {url}")
        response = self.pages[url]
        response.raise_for_status()
        return response


def reader_for(configs, pages, root=None):
    """Write connector configs to a temp dir and build a Reader on them."""
    directory = tempfile.mkdtemp()
    files = []
    for relative, config in configs.items():
        path = os.path.join(directory, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(config, fh)
        files.append(path)
    return Reader(sorted(files), root=directory if root is None else root, fetcher=FakeFetcher(pages))


def html_connector(**overrides):
    config = {
        "name": "Example",
        "source": "https://example.com",
        "paths": ["/news/"],
        "splitter": {"selector": "article"},
        "patterns": {"title": {"selector": "h2"}, "link": {"selector": "h2 a"}},
    }
    config.update(overrides)
    return config


class TextAndUrlTests(unittest.TestCase):
    def test_clean_text_spacing_and_invisible_characters(self):
        self.assertEqual(clean_text("Nov 05,​ 2026"), "Nov 05, 2026")
        self.assertEqual(clean_text("a 2021 essay , and ( note )"), "a 2021 essay, and (note)")

    def test_windows_1252_entities_become_real_characters(self):
        # &#151; / &#147; / &#148; parse to C1 control characters on old pages
        self.assertEqual(clean_text("Nov. 6 \x97 a \x93quote\x94"), "Nov. 6 — a “quote”")

    def test_inline_tags_keep_their_spaces(self):
        from bs4 import BeautifulSoup
        rule = Divisor({"selector": "p"})
        soup = BeautifulSoup("<div><p>In a 2021<a href='#'>essay</a>and my book, <i>A Mind</i>, I talk</p></div>", "lxml")
        self.assertEqual(rule.extract(soup.div), "In a 2021 essay and my book, A Mind, I talk")

    def test_srcset_picks_largest(self):
        self.assertEqual(best_from_srcset("a.jpg 320w, b.jpg 1024w, c.jpg 640w"), "b.jpg")
        self.assertEqual(best_from_srcset("a.jpg 1x, b.jpg 2x"), "b.jpg")
        self.assertEqual(best_from_srcset("only.jpg"), "only.jpg")

    def test_normalize_link_drops_tracking_and_fragment(self):
        self.assertEqual(
            normalize_link("HTTPS://Example.com/a?id=3&utm_source=x&fbclid=y#comments"),
            "https://example.com/a?id=3",
        )
        # Untouched query strings are kept byte for byte.
        self.assertEqual(normalize_link("https://x.com/i?src=a%2Fb"), "https://x.com/i?src=a%2Fb")


class DivisorTests(unittest.TestCase):
    def soup(self, markup):
        from bs4 import BeautifulSoup
        return BeautifulSoup(markup, "lxml").body

    def test_self_selector_reads_the_block_itself(self):
        block = self.soup('<a class="card" href="/post/1"><h3>Hi</h3></a>').a
        rule = Divisor({"selector": ":self", "attribute": "href"}, url_field=True, resolve_default=True)
        self.assertEqual(rule.extract(block, "https://example.com/news/"), "https://example.com/post/1")

    def test_selector_list_is_a_priority_order(self):
        block = self.soup('<div><span class="b">second</span><h2 class="a">first</h2></div>').div
        self.assertEqual(Divisor({"selector": ["h2.a", "span.b"]}).extract(block), "first")
        self.assertEqual(Divisor({"selector": ["h9", "span.b"]}).extract(block), "second")

    def test_empty_first_match_falls_through_to_next_match(self):
        block = self.soup('<div><a href="/x"></a><a href="/x">Real title</a></div>').div
        self.assertEqual(Divisor({"selector": "a"}).extract(block), "Real title")

    def test_image_skips_placeholders_and_reads_lazy_attributes(self):
        from Divisor import IMAGE_ATTRIBUTES
        rule = Divisor({"selector": "figure"}, default_attribute=IMAGE_ATTRIBUTES,
                       resolve_default=True, url_field=True, image_field=True)
        block = self.soup('<div><figure><img src="data:image/gif;base64,R0lG" data-src="/real.jpg"></figure></div>').div
        self.assertEqual(rule.extract(block, "https://example.com/"), "https://example.com/real.jpg")

    def test_explicit_src_only_returns_nothing_for_placeholder(self):
        rule = Divisor({"selector": "img", "attribute": ["src"]}, url_field=True, image_field=True)
        block = self.soup('<div><img src="data:image/gif;base64,R0lG" data-src="/real.jpg"></div>').div
        self.assertEqual(rule.extract(block), "")

    def test_relative_link_resolves_against_page_not_site_root(self):
        rule = Divisor({"selector": "a"}, default_attribute="href", resolve_default=True, url_field=True)
        block = self.soup('<div><a href="story-2">x</a></div>').div
        self.assertEqual(rule.extract(block, "https://example.com/category/news/"),
                         "https://example.com/category/news/story-2")

    def test_transform_regex_format_and_multiple(self):
        encoded = base64.b64encode(b"2 hours ago").decode()
        block = self.soup(f'<div><span data-ts="{encoded}"></span><a class="t">AI</a><a class="t">Cloud</a>'
                          f'<a class="t">AI</a><p>Posted on Nov 3, 2026 at 7:01</p><b>my-slug</b></div>').div
        self.assertEqual(Divisor({"selector": "span", "attribute": "data-ts", "transform": "base64"}).extract(block),
                         "2 hours ago")
        self.assertEqual(Divisor({"selector": "a.t", "multiple": True}).extract(block), "AI, Cloud")
        self.assertEqual(Divisor({"selector": "p", "regex": r"Posted on (.+?) at"}).extract(block), "Nov 3, 2026")
        rule = Divisor({"selector": "b", "format": "/blog/{}"}, resolve_default=True, url_field=True)
        self.assertEqual(rule.extract(block, "https://example.com/"), "https://example.com/blog/my-slug")

    def test_json_paths(self):
        item = {"headline": "Hello", "image": {"@type": "ImageObject", "url": "/i.png"},
                "tags": [{"name": "a"}, {"name": "b"}], "summary": "<p>Some <b>bold</b> text</p>"}
        self.assertEqual(Divisor({"path": "headline"}).extract(item), "Hello")
        self.assertEqual(Divisor({"path": ["missing", "summary"]}).extract(item), "Some bold text")
        self.assertEqual(Divisor({"path": "tags.*.name", "multiple": True}).extract(item), "a, b")
        rule = Divisor({"path": "image"}, resolve_default=True, url_field=True)
        self.assertEqual(rule.extract(item, "https://example.com/x/"), "https://example.com/i.png")


class ValidationTests(unittest.TestCase):
    def test_bad_selector_is_reported(self):
        with self.assertRaises(ConnectorError) as ctx:
            Connector(html_connector(patterns={"title": {"selector": "h2[["}}))
        self.assertIn("patterns.title", str(ctx.exception))

    def test_bad_regex_and_unknown_transform(self):
        with self.assertRaises(ConnectorError):
            Connector(html_connector(patterns={"title": {"selector": "h2", "regex": "("}}))
        with self.assertRaises(ConnectorError):
            Connector(html_connector(patterns={"title": {"selector": "h2", "transform": "rot13"}}))

    def test_unknown_keys_are_warnings(self):
        connector = Connector(html_connector(pattern={}, patterns={"title": {"selector": "h2", "selecter": "x"}}))
        self.assertTrue(any('"pattern"' in w for w in connector.warnings))
        self.assertTrue(any("patterns.title.selecter" in w for w in connector.warnings))

    def test_html_connector_needs_a_splitter(self):
        with self.assertRaises(ConnectorError):
            Connector(html_connector(splitter={}))

    def test_bad_timezone(self):
        with self.assertRaises(ConnectorError):
            Connector(html_connector(timezone="Mars/Olympus"))


class DateTests(unittest.TestCase):
    def test_iso_and_rfc2822(self):
        self.assertEqual(to_iso("2026-11-06T13:59:09Z", now=NOW), "2026-11-06T13:59:09Z")
        self.assertEqual(to_iso("2026-11-06 12:55:11.000000-0500", now=NOW), "2026-11-06T17:55:11Z")
        self.assertEqual(to_iso("Thu, 05 Nov 2026 14:00:00 GMT", now=NOW), "2026-11-05T14:00:00Z")

    def test_natural_language_dates(self):
        self.assertEqual(to_iso("2 hours ago", ["en"], now=NOW), "2026-11-06T10:00:00Z")
        self.assertEqual(to_iso("Nov. 5, 2026", ["en"], now=NOW), "2026-11-05T00:00:00Z")
        self.assertEqual(to_iso("Há 1 hora", ["pt"], now=NOW), "2026-11-06T11:00:00Z")
        self.assertEqual(to_iso("6 de novembro de 2026", ["pt"], now=NOW), "2026-11-06T00:00:00Z")

    def test_timezone_applies_to_naive_dates(self):
        self.assertEqual(to_iso("05.11.2026 às 18:02", ["pt"], "America/Sao_Paulo", now=NOW), "2026-11-05T21:02:00Z")

    def test_garbage_and_future_dates_are_empty(self):
        self.assertEqual(to_iso("By Jane Doe", ["en"], now=NOW), "")
        self.assertEqual(to_iso("2031-01-01T00:00:00Z", now=NOW), "")


class ReaderTests(unittest.TestCase):
    def test_charset_comes_from_meta_when_header_has_none(self):
        page = '<html><head><meta charset="utf-8"></head><body><article><h2><a href="/a">Administração</a></h2></article></body></html>'
        pages = {"https://example.com/news/": make_response("https://example.com/news/", page.encode("utf-8"),
                                                            content_type="text/html")}
        reader = reader_for({"c.json": html_connector()}, pages)
        self.assertEqual(reader.refresh()[0].title, "Administração")

    def test_limit_counts_across_all_paths(self):
        body = "<html><body>" + "".join(f'<article><h2><a href="/{p}{i}">t{p}{i}</a></h2></article>'
                                         for p in "x" for i in range(5)) + "</body></html>"
        other = body.replace("/x", "/y").replace("tx", "ty")
        pages = {"https://example.com/news/": make_response("https://example.com/news/", body),
                 "https://example.com/more/": make_response("https://example.com/more/", other)}
        reader = reader_for({"c.json": html_connector(paths=["/news/", "/more/"], limit=7)}, pages)
        self.assertEqual(len(reader.refresh()), 7)

    def test_sibling_grouping_and_exclude(self):
        page = """<html><body><div class="feed">
            <h2 class="hl">First story</h2><p>Summary one</p><a href="/1">Full Story</a>
            <h2 class="hl">Sponsored thing</h2><p>Presented by ACME</p><a href="/ad">Full Story</a>
            <h2 class="hl">Second story</h2><p>Summary two</p><a href="/2">Full Story</a>
        </div></body></html>"""
        config = html_connector(
            splitter={"selector": "h2.hl", "group": "siblings", "exclude_regex": "Presented by"},
            patterns={"title": {"selector": "h2"}, "description": {"selector": "p"},
                      "link": {"selector": "a:-soup-contains('Full Story')"}},
        )
        pages = {"https://example.com/news/": make_response("https://example.com/news/", page)}
        articles = reader_for({"c.json": config}, pages).refresh()
        self.assertEqual([a.title for a in articles], ["First story", "Second story"])
        self.assertEqual(articles[1].desc, "Summary two")
        self.assertEqual(articles[1].link, "https://example.com/2")

    def test_rss_feed_needs_no_patterns(self):
        feed = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/" xmlns:dc="http://purl.org/dc/elements/1.1/"
             xmlns:content="http://purl.org/rss/1.0/modules/content/">
        <channel><title>Feed</title>
          <item><title>Older &amp; wiser</title><link>https://example.com/old?utm_source=rss</link>
            <pubDate>Wed, 04 Nov 2026 10:00:00 +0000</pubDate><category>Cloud</category><category>AI</category>
            <description><![CDATA[<p>Hello <b>world</b></p>]]></description>
            <media:content url="https://cdn.example.com/old.jpg" medium="image"/></item>
          <item><title>Newer</title><link>https://example.com/new</link><dc:date>2026-11-05T09:00:00Z</dc:date>
            <content:encoded><![CDATA[<p>Body <img src="https://cdn.example.com/new.png"></p>]]></content:encoded></item>
        </channel></rss>"""
        config = {"name": "Feed", "source": "https://example.com", "type": "rss", "paths": ["/feed/"]}
        pages = {"https://example.com/feed/": make_response("https://example.com/feed/", feed, "application/rss+xml")}
        articles = reader_for({"c.json": config}, pages).refresh()
        self.assertEqual([a.title for a in articles], ["Newer", "Older & wiser"])  # newest first
        old = articles[1]
        self.assertEqual(old.link, "https://example.com/old")
        self.assertEqual(old.topic, "Cloud, AI")
        self.assertEqual(old.desc, "Hello world")
        self.assertEqual(old.image, "https://cdn.example.com/old.jpg")
        self.assertEqual(old.published, "2026-11-04T10:00:00Z")
        self.assertEqual(articles[0].image, "https://cdn.example.com/new.png")

    def test_feed_topics_are_capped_and_title_echo_is_not_a_description(self):
        categories = "".join(f"<category>t{i}</category>" for i in range(9))
        feed = (f'<?xml version="1.0"?><rss version="2.0"><channel><item><title>Same text</title>'
                f'<link>https://example.com/1</link><description>Same text</description>{categories}</item>'
                f'</channel></rss>')
        config = {"name": "Feed", "source": "https://example.com", "type": "rss", "paths": ["/feed"]}
        pages = {"https://example.com/feed": make_response("https://example.com/feed", feed, "application/rss+xml")}
        article = reader_for({"c.json": config}, pages).refresh()[0]
        self.assertEqual(article.topic, "t0, t1, t2, t3, t4")
        self.assertEqual(article.desc, "")

    def test_atom_feed(self):
        feed = """<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom">
          <entry><title type="html">Atom &lt;i&gt;post&lt;/i&gt;</title>
            <link rel="replies" href="https://example.com/p/1#comments"/>
            <link rel="alternate" href="https://example.com/p/1"/>
            <published>2026-11-05T08:00:00Z</published><summary>Short</summary>
            <category term="Linux"/></entry></feed>"""
        config = {"name": "Atom", "source": "https://example.com", "type": "rss", "paths": ["/atom.xml"]}
        pages = {"https://example.com/atom.xml": make_response("https://example.com/atom.xml", feed, "application/atom+xml")}
        article = reader_for({"c.json": config}, pages).refresh()[0]
        self.assertEqual((article.title, article.link, article.topic), ("Atom post", "https://example.com/p/1", "Linux"))

    def test_json_from_embedded_script(self):
        data = {"props": {"pageProps": {"posts": [
            {"title": "One", "slug": "one", "date": "2026-11-05T10:00:00Z", "kind": "post"},
            {"title": "Ad", "slug": "ad", "kind": "promo"},
        ]}}}
        page = f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></body></html>'
        config = {
            "name": "Next", "source": "https://example.com", "type": "json", "paths": ["/"],
            "json": {"script": "script#__NEXT_DATA__", "items": "props.pageProps.posts", "match": {"kind": "post"}},
            "patterns": {"title": {"path": "title"}, "date": {"path": "date"},
                         "link": {"path": "slug", "format": "/news/{}"}},
        }
        pages = {"https://example.com/": make_response("https://example.com/", page)}
        articles = reader_for({"c.json": config}, pages).refresh()
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].link, "https://example.com/news/one")

    def test_category_health_and_failures(self):
        good = make_response("https://example.com/news/", '<article><h2><a href="/a">A</a></h2></article>')
        empty = make_response("https://empty.com/news/", "<p>redesigned</p>")
        configs = {
            "games/good.json": html_connector(),
            "games/empty.json": html_connector(name="Empty", source="https://empty.com"),
            "world/down.json": html_connector(name="Down", source="https://down.com"),
            "broken.json": html_connector(patterns={"title": {"selector": "h2[["}}),
        }
        reader = reader_for(configs, {"https://example.com/news/": good, "https://empty.com/news/": empty})
        articles = reader.refresh()
        self.assertEqual([(a.title, a.category) for a in articles], [("A", "games")])
        statuses = {s["name"]: s["health"]["status"] for s in reader.sources()}
        self.assertEqual(statuses, {"Example": "ok", "Empty": "empty", "Down": "error"})
        self.assertEqual(len(reader.skipped), 1)
        self.assertEqual(reader.health_summary()["status"], "degraded")

    def test_concurrent_callers_share_one_scrape(self):
        import threading
        page = make_response("https://example.com/news/", '<article><h2><a href="/a">A</a></h2></article>')
        reader = reader_for({"c.json": html_connector()}, {"https://example.com/news/": page})
        threads = [threading.Thread(target=reader.get_articles) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(reader.fetcher.requested), 1)


class ApiTests(unittest.TestCase):
    def test_filters(self):
        os.environ["BACKGROUND_REFRESH"] = "false"
        import main
        page = make_response("https://example.com/news/",
                             '<article><h2><a href="/a">Ransomware hits</a></h2><time>2026-11-05T10:00:00Z</time></article>'
                             '<article><h2><a href="/b">Old news</a></h2><time>2026-10-01T10:00:00Z</time></article>')
        main.reader = reader_for({"security/c.json": html_connector(patterns={
            "title": {"selector": "h2"}, "link": {"selector": "h2 a"}, "date": {"selector": "time"}})},
            {"https://example.com/news/": page})
        client = main.app.test_client()
        body = client.get("/news?category=security&since=2026-11-01").get_json()
        self.assertEqual([a["title"] for a in body["articles"]], ["Ransomware hits"])
        self.assertEqual(client.get("/news?category=games").get_json()["count"], 0)
        self.assertEqual(client.get("/news?q=old").get_json()["count"], 1)
        self.assertEqual(client.get("/health").get_json()["status"], "ok")


if __name__ == "__main__":
    unittest.main()

"""Turning a fetched page into article items, for each connector type.

    html -> article blocks cut out of the page by the connector's splitter
    rss  -> <item> (RSS) / <entry> (Atom) elements of a feed; every field has
            a built-in default, so a feed connector needs no patterns at all
    json -> objects found inside JSON: either the response itself (an API) or
            <script> tags embedded in the page (__NEXT_DATA__, JSON-LD...)
"""

import json
import textwrap

from bs4 import BeautifulSoup

from Divisor import json_walk, resolve_url, strip_html
from Fetcher import markup_of

FEED_DESCRIPTION_LIMIT = 500
FEED_TOPIC_LIMIT = 5  # feeds often list a dozen tags; keep the leading ones
_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif")


# ---- html ------------------------------------------------------------------

def html_blocks(response, connector):
    """Return (blocks, base_url) for an HTML page."""
    soup = BeautifulSoup(markup_of(response), connector.parser)
    base_url = response.url
    base = soup.find("base", href=True)
    if base:
        base_url = resolve_url(base["href"], response.url)
    return connector.splitter.split(soup), base_url


# ---- rss / atom ------------------------------------------------------------

def _children(item, name, prefix=None):
    """Direct children called `name` with the given namespace prefix.

    Elements in a feed's default namespace (Atom) have the prefix "", plain
    RSS elements have None; both count as "no prefix".
    """
    return [c for c in item.find_all(name, recursive=False) if (c.prefix or None) == prefix]


def _first_text(item, *candidates):
    for name, prefix in candidates:
        for child in _children(item, name, prefix):
            text = child.get_text()
            if text and text.strip():
                return text.strip()
    return ""


def _feed_link(item):
    # FeedBurner keeps the publisher's real URL here.
    original = _first_text(item, ("origLink", "feedburner"))
    if original:
        return original
    for link in _children(item, "link") + _children(item, "link", "atom"):
        href = link.get("href")
        if href:
            if link.get("rel", "alternate") == "alternate":
                return href.strip()
            continue
        text = link.get_text().strip()
        if text:
            return text
    for guid in _children(item, "guid"):
        text = guid.get_text().strip()
        if guid.get("isPermaLink", "true") != "false" and text.startswith("http"):
            return text
    for link in _children(item, "link") + _children(item, "link", "atom"):
        if link.get("href"):
            return link["href"].strip()
    return ""


def _feed_image(item, html_fields):
    def looks_like_image(tag):
        kind = (tag.get("medium") or tag.get("type") or "").lower()
        url = (tag.get("url") or "").lower().split("?")[0]
        return kind.startswith("image") or url.endswith(_IMAGE_EXTENSIONS)

    groups = _children(item, "group", "media")
    for scope in [item] + groups:
        for tag in _children(scope, "thumbnail", "media"):
            if tag.get("url"):
                return tag["url"]
        for tag in _children(scope, "content", "media"):
            if tag.get("url") and looks_like_image(tag):
                return tag["url"]
    for tag in _children(item, "enclosure"):
        if tag.get("url") and looks_like_image(tag):
            return tag["url"]
    for tag in _children(item, "image", "itunes"):
        if tag.get("href"):
            return tag["href"]
    # Last resort: the first picture inside the post's HTML.
    for raw in html_fields:
        if raw and "<img" in raw:
            img = BeautifulSoup(raw, "lxml").find("img", src=True)
            if img and not img["src"].startswith("data:"):
                return img["src"]
    return ""


def feed_entries(response):
    """Return [(element, defaults)] for every item of an RSS/Atom feed."""
    soup = BeautifulSoup(response.content, "xml")
    items = soup.find_all("item") or soup.find_all("entry")
    entries = []
    for item in items:
        summary_html = _first_text(item, ("description", None), ("summary", None))
        content_html = _first_text(item, ("encoded", "content"), ("content", None))

        description = strip_html(summary_html or content_html)
        if len(description) > FEED_DESCRIPTION_LIMIT:
            description = textwrap.shorten(description, FEED_DESCRIPTION_LIMIT, placeholder="…")

        topics = []
        for category in _children(item, "category") + _children(item, "subject", "dc"):
            value = (category.get("term") or category.get_text() or "").strip()
            if value and value not in topics:
                topics.append(value)

        defaults = {
            "title": strip_html(_first_text(item, ("title", None))),
            "description": description,
            "date": _first_text(item, ("pubDate", None), ("published", None), ("updated", None),
                                ("date", "dc"), ("issued", None)),
            "link": _feed_link(item),
            "topic": ", ".join(topics[:FEED_TOPIC_LIMIT]),
            "image": _feed_image(item, (summary_html, content_html)),
        }
        entries.append((item, defaults))
    return entries


# ---- json ------------------------------------------------------------------

def _matches(item, wanted):
    for key, expected in wanted.items():
        actual = item.get(key)
        expected_list = expected if isinstance(expected, list) else [expected]
        actual_list = actual if isinstance(actual, list) else [actual]
        if not any(a in expected_list for a in actual_list):
            return False
    return True


def json_items(response, connector):
    """Return the JSON objects that represent articles."""
    options = connector.json
    documents = []
    if options.get("script"):
        soup = BeautifulSoup(markup_of(response), connector.parser)
        for script in soup.select(options["script"]):
            try:
                documents.append(json.loads(script.string or script.get_text()))
            except (TypeError, ValueError):
                continue
    else:
        documents.append(json.loads(response.content))

    items = []
    for document in documents:
        for found in json_walk(document, options.get("items", "")):
            items.extend(found if isinstance(found, list) else [found])

    items = [item for item in items if isinstance(item, dict)]
    if options.get("match"):
        items = [item for item in items if _matches(item, options["match"])]
    return items

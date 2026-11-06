"""Field extraction rule for a connector.

A Divisor describes HOW to locate a piece of data inside one article block and
what to pull out of it. It is intentionally declarative so the whole thing can
be expressed as JSON by someone who has never seen the Python side.

Supported JSON keys (all optional):

    selector   -> a CSS selector, or a list of selectors tried in order until
                  one yields a value. ":self" means the block itself.
    path       -> for JSON connectors: a dotted path inside one item, e.g.
                  "headline" or "image.url" (a list = fallbacks, like selector)
    html_tag   -> legacy way to pick a tag, e.g. "h2"
    html_class -> legacy class filter used together with html_tag
    attribute  -> which attribute to read: "href", "src", "datetime", ...
                  Use "text" (the default for most fields) for the inner text.
                  May be a list to try several in order: ["data-src", "src"].
    transform  -> post-processing step(s): "base64", "lower", "upper",
                  "strip_query" (a single name or a list, applied in order)
    regex      -> regex applied to the value. If it has a capturing group,
                  group(1) is kept, otherwise the whole match.
    format     -> template the value is placed into, "{}" marks the spot,
                  e.g. "/blog/{}" to turn a slug into a path
    multiple   -> true to collect every match instead of the first one
    separator  -> how multiple values are joined (default ", ")
    resolve    -> true/false, turn a relative URL into an absolute one.
                  Defaults to true for url-like fields.

An empty Divisor (no selector / path / html_tag) means "this field is not used"
and simply yields an empty string.
"""

import base64
import binascii
import html
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

import soupsieve
from bs4 import BeautifulSoup

SELF = ":self"

KNOWN_KEYS = {
    "selector", "path", "html_tag", "html_class", "attribute", "transform",
    "regex", "format", "multiple", "separator", "resolve",
}

# Lazy-loading sites hide the real image in many different attributes. A
# "data:" placeholder in an earlier attribute is skipped, so the order only
# decides between real URLs.
IMAGE_ATTRIBUTES = [
    "data-src", "data-lazy-src", "data-original", "data-src-img", "src",
    "data-srcset", "data-lazy-srcset", "srcset",
]

# Values that are never a real link or image.
_NOT_A_URL = ("data:", "javascript:", "about:", "#", "mailto:")

# Icon-font glyphs (private use area) and invisible characters that leak into
# scraped text, e.g. the clock icon in front of a date.
_INVISIBLE = re.compile("[-​-‍⁠﻿­]")
# Old pages write Windows-1252 codes as entities (&#151; for an em dash); the
# parser turns them into invisible C1 control characters. Map them back.
_C1_CONTROLS = re.compile("[\x80-\x9f]")
_SPACES = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?%)\]}])")
_SPACE_AFTER_OPEN = re.compile(r"([(\[{])\s+")
_LOOKS_LIKE_HTML = re.compile(r"<[a-zA-Z/!][^>]*>")
_SRCSET_DESCRIPTOR = re.compile(r"^([\d.]+)([wxh]),?$")


def clean_text(value):
    """Normalise whitespace and drop invisible characters."""
    if not value:
        return ""
    value = _C1_CONTROLS.sub(lambda m: bytes([ord(m.group())]).decode("cp1252", errors="ignore"), value)
    value = _INVISIBLE.sub("", value.replace("\xa0", " "))
    value = _SPACES.sub(" ", value).strip()
    # get_text(" ") puts a space between every text node, which leaves
    # "word , word" behind inline tags. Glue punctuation back on.
    value = _SPACE_BEFORE_PUNCT.sub(r"\1", value)
    return _SPACE_AFTER_OPEN.sub(r"\1", value)


def strip_html(value):
    """Turn a string that may contain HTML (RSS, JSON) into plain text."""
    if not value:
        return ""
    if _LOOKS_LIKE_HTML.search(value):
        value = BeautifulSoup(value, "lxml").get_text(" ")
    else:
        value = html.unescape(value)
    return clean_text(value)


def best_from_srcset(srcset):
    """Pick the largest candidate of a srcset ("a.jpg 320w, b.jpg 640w")."""
    tokens = srcset.split()
    best_url, best_size = "", -1.0
    i = 0
    while i < len(tokens):
        url = tokens[i]
        i += 1
        size = 0.0
        if url.endswith(","):
            url = url[:-1]
        elif i < len(tokens):
            match = _SRCSET_DESCRIPTOR.match(tokens[i])
            if match:
                i += 1
                number = float(match.group(1))
                size = number if match.group(2) == "w" else number * 1000
        if url and size > best_size:
            best_url, best_size = url, size
    return best_url


def resolve_url(value, base):
    """Make a relative URL absolute against the page it was found on."""
    if not value or not base:
        return value
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("//"):
        return (urlsplit(base).scheme or "https") + ":" + value
    return urljoin(base, value)


def json_walk(data, path):
    """Yield every value found at a dotted path ("a.b.*.c") inside JSON data."""
    if path in ("", "$", SELF):
        yield data
        return
    current = [data]
    for part in path.split("."):
        found = []
        for node in current:
            if part == "*":
                if isinstance(node, list):
                    found.extend(node)
                elif isinstance(node, dict):
                    found.extend(node.values())
            elif isinstance(node, dict):
                if part in node:
                    found.append(node[part])
            elif isinstance(node, list) and part.lstrip("-").isdigit():
                index = int(part)
                if -len(node) <= index < len(node):
                    found.append(node[index])
        current = found
    yield from current


def _strip_query(value):
    parts = urlsplit(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _base64(value):
    # Accept both the standard and the URL-safe alphabet, with or without padding.
    value = value.strip().replace("-", "+").replace("_", "/")
    try:
        return base64.b64decode(value + "=" * (-len(value) % 4), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return ""


TRANSFORMS = {
    "base64": _base64,
    "lower": str.lower,
    "upper": str.upper,
    "strip_query": _strip_query,
}


def _as_list(value):
    if value is None or value == "":
        return []
    return [value] if isinstance(value, str) else list(value)


class Divisor:
    def __init__(self, config=None, *, default_attribute="text", resolve_default=False,
                 url_field=False, image_field=False):
        config = config or {}

        # Allow the very old form where a Divisor was built from (tag, class).
        if isinstance(config, str):
            config = {"html_tag": config}

        self.unknown_keys = sorted(set(config) - KNOWN_KEYS)

        self.selectors = _as_list(config.get("selector"))
        self.paths = _as_list(config.get("path"))
        self.html_tag = config.get("html_tag", "") or ""
        self.html_class = config.get("html_class", "") or ""

        self.attributes = _as_list(config.get("attribute", default_attribute))
        self.transforms = _as_list(config.get("transform"))
        self.format = config.get("format") or None
        self.multiple = bool(config.get("multiple", False))
        self.separator = config.get("separator", ", ")
        self.resolve = config.get("resolve", resolve_default)

        self.url_field = url_field
        self.image_field = image_field

        self._compiled = {}
        for selector in self.selectors:
            if selector == SELF:
                continue
            try:
                self._compiled[selector] = soupsieve.compile(selector)
            except Exception as exc:
                raise ValueError(f"invalid CSS selector {selector!r}: {exc}") from exc

        for name in self.transforms:
            if name not in TRANSFORMS:
                raise ValueError(f"unknown transform {name!r} (use one of {', '.join(TRANSFORMS)})")

        try:
            self.regex = re.compile(config["regex"]) if config.get("regex") else None
        except re.error as exc:
            raise ValueError(f"invalid regex {config['regex']!r}: {exc}") from exc

    @property
    def is_active(self):
        """Whether this field should be extracted at all."""
        return bool(self.selectors or self.paths or self.html_tag)

    # ---- locating ----------------------------------------------------------

    def _find(self, element):
        """Yield candidate tags, selector by selector, in priority order."""
        if self.selectors:
            for selector in self.selectors:
                if selector == SELF:
                    yield element
                else:
                    yield from self._compiled[selector].iselect(element)
                # Remember which selector produced candidates so a later,
                # lower-priority selector is only used as a fallback.
                yield None
            return
        if self.html_tag:
            kwargs = {"class_": self.html_class} if self.html_class else {}
            yield from element.find_all(self.html_tag, **kwargs)

    def _read_value(self, tag):
        """Pull the configured attribute (or text) out of a found tag."""
        candidates = [tag]
        # An image selector may point at a <picture>, <figure> or wrapper
        # instead of the <img> itself; look inside it too.
        if self.image_field and tag.name not in ("img", "source"):
            candidates += tag.select("img, source")

        for candidate in candidates:
            for attr in self.attributes:
                if attr == "text":
                    text = candidate.get_text(" ", strip=True)
                    if text:
                        return text
                    continue
                value = candidate.get(attr)
                if isinstance(value, list):  # e.g. class
                    value = " ".join(value)
                if not value or not value.strip():
                    continue
                value = value.strip()
                if "srcset" in attr:
                    value = best_from_srcset(value)
                if self.url_field and value.lower().startswith(_NOT_A_URL):
                    continue
                return value
        return ""

    # ---- post-processing ---------------------------------------------------

    def _finish(self, value, base_url):
        if self.url_field:
            value = value.strip()
        else:
            value = strip_html(value)

        for name in self.transforms:
            value = TRANSFORMS[name](value)
            if not self.url_field:
                value = clean_text(value)

        if value and self.regex:
            match = self.regex.search(value)
            if not match:
                return ""
            value = (match.group(1) if match.groups() else match.group(0)) or ""
            value = value.strip()

        if value and self.format:
            value = self.format.replace("{}", value)

        if value and self.resolve and base_url:
            value = resolve_url(value, base_url)
        return value

    @staticmethod
    def _json_to_strings(value):
        """Flatten a JSON value into strings (lists -> items, objects -> url/name)."""
        if value is None or value == "":
            return []
        if isinstance(value, list):
            out = []
            for item in value:
                out.extend(Divisor._json_to_strings(item))
            return out
        if isinstance(value, dict):
            for key in ("url", "href", "src", "name", "text", "@id"):
                if value.get(key):
                    return Divisor._json_to_strings(value[key])
            return []
        if isinstance(value, bool):
            return []
        return [str(value)]

    def _values(self, element, base_url):
        """Yield finished, non-empty values in priority order."""
        if isinstance(element, (dict, list)):
            for path in self.paths:
                produced = False
                for found in json_walk(element, path):
                    for raw in self._json_to_strings(found):
                        value = self._finish(raw, base_url)
                        if value:
                            produced = True
                            yield value
                if produced and not self.multiple:
                    return
            return

        produced = False
        for tag in self._find(element):
            if tag is None:  # end of one selector's candidates
                if produced:
                    return
                continue
            raw = self._read_value(tag)
            if not raw:
                continue
            value = self._finish(raw, base_url)
            if value:
                produced = True
                yield value
                if not self.multiple:
                    return

    def extract(self, element, base_url=""):
        """Extract this field's value from an article block (or JSON item).

        Returns an empty string if the field is inactive or nothing matches,
        so a single missing field never kills the whole article.
        """
        if not self.is_active:
            return ""
        values = []
        for value in self._values(element, base_url):
            if value not in values:
                values.append(value)
            if not self.multiple:
                break
        return self.separator.join(values) if self.multiple else (values[0] if values else "")

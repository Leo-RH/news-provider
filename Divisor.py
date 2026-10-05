"""Field extraction rule for a connector.

A Divisor describes HOW to locate a piece of data inside a chunk of HTML and
what to pull out of it. It is intentionally tiny and declarative so the whole
thing can be expressed as JSON by someone who has never seen the Python side.

Supported JSON keys (all optional):

    selector   -> a CSS selector, e.g. "h2.home-title" or "a.story-link"
    html_tag   -> legacy way to pick a tag, e.g. "h2"
    html_class -> legacy class filter used together with html_tag
    attribute  -> which attribute to read: "href", "src", "data-src", ...
                  Use "text" (the default for most fields) to read inner text.
                  May be a list to try several in order: ["data-src", "src"].
    regex      -> regex applied to the extracted value. If it has a capturing
                  group, group(1) is kept, otherwise the whole match.
    resolve    -> true/false, turn a relative URL into an absolute one using
                  the connector's source. Defaults to true for url-like fields.

An empty Divisor (no selector / no html_tag) means "this field is not used"
and simply yields an empty string.
"""

import re
from urllib.parse import urljoin


class Divisor:
    # attributes tried, in order, when a url field doesn't specify one
    _URL_ATTR_FALLBACKS = ["href", "data-src", "data-lazy-src", "data-original", "src", "srcset"]

    def __init__(self, config=None, *, default_attribute="text", resolve_default=False):
        config = config or {}

        # Allow the very old form where a Divisor was built from (tag, class).
        if isinstance(config, str):
            config = {"html_tag": config}

        self.selector = config.get("selector", "") or ""
        self.html_tag = config.get("html_tag", "") or ""
        self.html_class = config.get("html_class", "") or ""

        attribute = config.get("attribute", default_attribute)
        self.attributes = [attribute] if isinstance(attribute, str) else list(attribute)

        self.regex = config.get("regex") or None
        self.resolve = config.get("resolve", resolve_default)

    @property
    def is_active(self):
        """Whether this field should be extracted at all."""
        return bool(self.selector or self.html_tag)

    def _find(self, element):
        """Return the first matching sub-element, or None."""
        if self.selector:
            return element.select_one(self.selector)
        if self.html_tag:
            kwargs = {}
            if self.html_class:
                kwargs["class_"] = self.html_class
            return element.find(self.html_tag, **kwargs)
        return None

    def _read_value(self, tag):
        """Pull the configured attribute (or text) out of a found tag."""
        for attr in self.attributes:
            if attr == "text":
                text = tag.get_text(strip=True)
                if text:
                    return text
                continue
            value = tag.get(attr)
            if not value:
                continue
            # srcset is "url1 1x, url2 2x" -> take the first url
            if attr == "srcset":
                value = value.split(",")[0].strip().split(" ")[0]
            return value
        return ""

    def extract(self, element, source=""):
        """Extract this field's value from a container element.

        Returns an empty string if the field is inactive or nothing matches,
        so a single missing field never kills the whole article.
        """
        if not self.is_active:
            return ""

        tag = self._find(element)
        if tag is None:
            return ""

        value = self._read_value(tag)
        if not value:
            return ""

        value = value.strip()

        if self.regex:
            match = re.search(self.regex, value)
            if not match:
                return ""
            value = match.group(1) if match.groups() else match.group(0)
            value = value.strip()

        if value and self.resolve and source:
            value = self._resolve_url(value, source)

        return value

    @staticmethod
    def _resolve_url(value, source):
        if value.startswith(("http://", "https://", "data:")):
            return value
        if value.startswith("//"):
            return "https:" + value
        return urljoin(source, value)

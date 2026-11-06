"""How a page is cut into article blocks.

Supported JSON keys of a connector's "splitter":

    selector      -> CSS selector matching one block per article (or a list
                     of selectors, whose matches are combined in page order)
    html_tag / html_class -> legacy alternative to "selector"
    group         -> "siblings": for pages without a wrapper per article.
                     Each match starts a block that also holds the elements
                     after it, up to the next match (e.g. a headline followed
                     by its summary paragraph and "read more" link).
    exclude       -> CSS selector (or list). A block that matches it, or
                     contains a match, is skipped (ads, sponsored posts...).
    exclude_regex -> regex. A block whose text matches it is skipped.
"""

import copy
import re

import soupsieve
from bs4 import Tag

KNOWN_KEYS = {"selector", "html_tag", "html_class", "group", "exclude", "exclude_regex"}
GROUPS = ("siblings",)


def _as_list(value):
    if value is None or value == "":
        return []
    return [value] if isinstance(value, str) else list(value)


def _compile(selector, what):
    try:
        return soupsieve.compile(selector)
    except Exception as exc:
        raise ValueError(f"invalid CSS selector in {what} {selector!r}: {exc}") from exc


class Splitter:
    def __init__(self, config=None):
        config = config or {}
        self.unknown_keys = sorted(set(config) - KNOWN_KEYS)

        self.selectors = _as_list(config.get("selector"))
        self.html_tag = config.get("html_tag", "") or ""
        self.html_class = config.get("html_class", "") or ""
        self.group = config.get("group") or None
        if self.group is not None and self.group not in GROUPS:
            raise ValueError(f"unknown group {self.group!r} (use one of {', '.join(GROUPS)})")

        self._match = _compile(", ".join(self.selectors), "splitter.selector") if self.selectors else None
        self._exclude = [_compile(s, "splitter.exclude") for s in _as_list(config.get("exclude"))]
        try:
            self._exclude_regex = re.compile(config["exclude_regex"]) if config.get("exclude_regex") else None
        except re.error as exc:
            raise ValueError(f"invalid splitter.exclude_regex: {exc}") from exc

    @property
    def is_active(self):
        return bool(self._match or self.html_tag)

    def split(self, soup):
        """Return the article blocks of a parsed page."""
        if self._match is not None:
            matches = self._match.select(soup)
        else:
            kwargs = {"class_": self.html_class} if self.html_class else {}
            matches = soup.find_all(self.html_tag or True, **kwargs)

        blocks = self._group_siblings(soup, matches) if self.group == "siblings" else matches
        return [block for block in blocks if not self._excluded(block)]

    @staticmethod
    def _group_siblings(soup, starts):
        """Wrap every start element and the siblings that follow it."""
        start_ids = {id(tag) for tag in starts}
        blocks = []
        for start in starts:
            wrapper = soup.new_tag("div")
            wrapper.append(copy.copy(start))
            for sibling in start.next_siblings:
                if id(sibling) in start_ids:
                    break
                if isinstance(sibling, Tag) and any(id(t) in start_ids for t in sibling.find_all(True)):
                    break
                wrapper.append(copy.copy(sibling))
            blocks.append(wrapper)
        return blocks

    def _excluded(self, block):
        for pattern in self._exclude:
            if pattern.match(block) or pattern.select_one(block) is not None:
                return True
        if self._exclude_regex and self._exclude_regex.search(block.get_text(" ", strip=True)):
            return True
        return False

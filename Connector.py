"""A Connector is a single news source described entirely by a JSON file.

It knows where to fetch pages from, how to split a page into article blocks,
and how to pull each field out of a block. All of that comes from the JSON, so
adding a new site never requires touching Python.

The JSON is validated when it is loaded: a typo'd key or a broken CSS
selector / regex is reported with the connector's file name instead of
silently producing zero articles.
"""

from Dates import zone
from Divisor import IMAGE_ATTRIBUTES, Divisor
from Splitter import Splitter

TYPES = ("html", "rss", "json")
PARSERS = ("lxml", "html.parser")

KNOWN_KEYS = {
    "name", "source", "paths", "type", "limit", "request", "splitter", "patterns",
    "json", "language", "timezone", "category", "parser", "enabled",
}
JSON_KEYS = {"script", "items", "match"}
REQUEST_KEYS = {"timeout", "headers"}

# The fields every article can have. For each we pick sensible defaults so a
# connector author only has to override what the site actually needs:
#   default_attribute -> what to read when the JSON doesn't say
#   resolve           -> whether relative URLs get turned into absolute ones
FIELD_DEFAULTS = {
    "title":       {"default_attribute": "text", "resolve": False},
    "description": {"default_attribute": "text", "resolve": False},
    "date":        {"default_attribute": "text", "resolve": False},
    "link":        {"default_attribute": "href", "resolve": True},
    "topic":       {"default_attribute": "text", "resolve": False},
    "image":       {"default_attribute": IMAGE_ATTRIBUTES, "resolve": True},
}

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


class ConnectorError(ValueError):
    """The connector JSON is unusable."""


def _as_list(value):
    if value is None or value == "":
        return []
    return [value] if isinstance(value, str) else list(value)


class Connector:
    def __init__(self, config, *, category="", origin=""):
        if not isinstance(config, dict):
            raise ConnectorError("a connector must be a JSON object")

        self.origin = origin
        self.warnings = []
        self._warn_unknown("", set(config) - KNOWN_KEYS)

        if not config.get("source"):
            raise ConnectorError('missing required key "source"')
        self.name = config.get("name") or config["source"]
        self.source = config["source"].rstrip("/")
        self.type = config.get("type", "html")
        if self.type not in TYPES:
            raise ConnectorError(f'unknown type {self.type!r} (use one of {", ".join(TYPES)})')

        self.paths = _as_list(config.get("paths", ["/"]))
        if not self.paths or not all(isinstance(p, str) for p in self.paths):
            raise ConnectorError('"paths" must be a list of strings')

        self.limit = config.get("limit")  # optional cap on articles per source
        if self.limit is not None and (not isinstance(self.limit, int) or self.limit < 1):
            raise ConnectorError('"limit" must be a positive integer')

        self.enabled = bool(config.get("enabled", True))
        self.category = config.get("category") or category
        self.language = _as_list(config.get("language")) or ["en"]
        self.timezone = config.get("timezone", "UTC")
        try:
            zone(self.timezone)
        except ValueError as exc:
            raise ConnectorError(str(exc)) from exc

        self.parser = config.get("parser", "lxml")
        if self.parser not in PARSERS:
            raise ConnectorError(f'unknown parser {self.parser!r} (use one of {", ".join(PARSERS)})')

        request_cfg = config.get("request", {})
        self._warn_unknown("request.", set(request_cfg) - REQUEST_KEYS)
        self.timeout = request_cfg.get("timeout", 15)
        self.headers = {**DEFAULT_HEADERS, **request_cfg.get("headers", {})}

        self.json = config.get("json") or {}
        self._warn_unknown("json.", set(self.json) - JSON_KEYS)

        try:
            self.splitter = Splitter(config.get("splitter", {}))
        except ValueError as exc:
            raise ConnectorError(str(exc)) from exc
        self._warn_unknown("splitter.", set(self.splitter.unknown_keys))

        patterns = config.get("patterns", {})
        self._warn_unknown("patterns.", set(patterns) - set(FIELD_DEFAULTS))
        self.fields = {}
        for field, defaults in FIELD_DEFAULTS.items():
            try:
                divisor = Divisor(
                    patterns.get(field, {}),
                    default_attribute=defaults["default_attribute"],
                    resolve_default=defaults["resolve"],
                    url_field=field in ("link", "image"),
                    image_field=field == "image",
                )
            except ValueError as exc:
                raise ConnectorError(f"patterns.{field}: {exc}") from exc
            self._warn_unknown(f"patterns.{field}.", set(divisor.unknown_keys))
            self.fields[field] = divisor

        self._check_type_requirements()

    def _warn_unknown(self, prefix, keys):
        for key in sorted(keys):
            self.warnings.append(f'unknown key "{prefix}{key}" is ignored')

    def _check_type_requirements(self):
        active = [f for f, d in self.fields.items() if d.is_active]
        if self.type == "html":
            if not self.splitter.is_active:
                raise ConnectorError('an html connector needs a "splitter" with a "selector"')
            if not active:
                raise ConnectorError('an html connector needs at least one field in "patterns"')
        elif self.type == "json":
            if not active:
                raise ConnectorError('a json connector needs "patterns" with "path" rules')
            for field in active:
                if not self.fields[field].paths:
                    raise ConnectorError(f'patterns.{field}: json connectors read fields with "path", not "selector"')

    def urls(self):
        """Yield the fully-qualified URLs this connector should crawl."""
        for path in self.paths:
            if path.startswith(("http://", "https://")):
                yield path
            else:
                yield self.source + ("" if path.startswith("/") else "/") + path

    def __repr__(self):
        return f"<Connector {self.name} ({self.source})>"

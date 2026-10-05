"""A Connector is a single news source described entirely by a JSON file.

It knows where to fetch pages from, how to split a page into article blocks,
and how to pull each field out of a block. All of that comes from the JSON, so
adding a new site never requires touching Python.
"""

from Divisor import Divisor

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
    "image":       {"default_attribute": ["data-src", "data-lazy-src", "src", "srcset"], "resolve": True},
}

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


class Connector:
    def __init__(self, config):
        self.name = config.get("name") or config.get("source", "unknown")
        self.source = config["source"].rstrip("/")
        self.paths = config.get("paths", ["/"])
        self.limit = config.get("limit")  # optional cap on articles per source

        request_cfg = config.get("request", {})
        self.timeout = request_cfg.get("timeout", 15)
        self.headers = {**DEFAULT_HEADERS, **request_cfg.get("headers", {})}

        self.splitter = Divisor(config.get("splitter", {}))

        patterns = config.get("patterns", {})
        self.fields = {}
        for field, defaults in FIELD_DEFAULTS.items():
            self.fields[field] = Divisor(
                patterns.get(field, {}),
                default_attribute=defaults["default_attribute"],
                resolve_default=defaults["resolve"],
            )

    def urls(self):
        """Yield the fully-qualified URLs this connector should crawl."""
        for path in self.paths:
            if path.startswith(("http://", "https://")):
                yield path
            else:
                yield self.source + ("" if path.startswith("/") else "/") + path

    def __repr__(self):
        return f"<Connector {self.name} ({self.source})>"

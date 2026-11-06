import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query parameters that only exist for click tracking; the same article shared
# with and without them must count as one.
_TRACKING_PARAM = re.compile(
    r"^(utm_\w+|fbclid|gclid|dclid|msclkid|mc_cid|mc_eid|ref_src|cmpid|ocid|_hsenc|_hsmi|mkt_tok)$",
    re.IGNORECASE,
)


def normalize_link(url):
    """Drop the #fragment and tracking parameters, lowercase the host."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    query = parts.query
    if query:
        params = parse_qsl(query, keep_blank_values=True)
        kept = [(k, v) for k, v in params if not _TRACKING_PARAM.match(k)]
        if len(kept) != len(params):  # only rebuild when something was removed
            query = urlencode(kept, doseq=True)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, query, ""))


class Article:
    def __init__(self, title, desc, date, link, topic, image, source, source_name="",
                 category="", published=""):
        self.title = title
        self.desc = desc
        self.date = date
        self.link = normalize_link(link)
        self.topic = topic
        self.image = image
        self.source = source
        self.source_name = source_name or source
        self.category = category
        self.published = published  # ISO 8601 UTC, "" when the date is unknown

    @property
    def is_valid(self):
        """An article is worth keeping if it has at least a title or a link."""
        return bool(self.title or self.link)

    @property
    def dedup_key(self):
        """Identity used to drop duplicates across pages/paths/sources."""
        if self.link:
            return self.link.lower().rstrip("/")
        return (self.title or "").strip().lower()

    def to_dict(self):
        return {
            "title": self.title,
            "description": self.desc,
            "date": self.date,
            "published": self.published,
            "link": self.link,
            "topic": self.topic,
            "image": self.image,
            "category": self.category,
            "source": self.source,
            "source_name": self.source_name,
        }

    def show(self):
        print("Title: " + self.title)
        print("Description: " + self.desc)
        print("Date: " + self.date)
        print("Published: " + self.published)
        print("Link: " + self.link)
        print("Topic: " + self.topic)
        print("Image: " + self.image)
        print("Category: " + self.category)

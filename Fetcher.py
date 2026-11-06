"""HTTP side of the engine: one shared session, retries, politeness.

* transient failures (connection errors, 429, 5xx) are retried with backoff,
  honouring the server's Retry-After (capped so a worker is never parked for
  long);
* at most `per_host` requests run against the same host at once;
* optionally, robots.txt is checked before every request.
"""

import logging
import threading
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger("news_provider")

# Use the operating system's trust store for TLS verification. This lets the
# scraper work behind corporate proxies / antivirus HTTPS inspection, whose
# root certificates live in the OS store but not in certifi's bundle. Harmless
# (and simply skipped) if the package isn't installed.
try:
    import truststore

    truststore.inject_into_ssl()
except Exception as exc:  # pragma: no cover - environment dependent
    log.debug("truststore not active: %s", exc)


class RobotsDisallowed(Exception):
    """The site's robots.txt does not allow fetching this URL."""


class _PoliteRetry(Retry):
    MAX_RETRY_AFTER = 30  # seconds

    def get_retry_after(self, response):
        seconds = super().get_retry_after(response)
        return None if seconds is None else min(seconds, self.MAX_RETRY_AFTER)


def markup_of(response):
    """What to hand to BeautifulSoup for a response.

    When the server declares a charset, trust it. Otherwise pass the raw bytes
    so the parser can read the page's own <meta charset> instead of requests'
    ISO-8859-1 fallback (which garbles every accented character).
    """
    content_type = response.headers.get("Content-Type", "").lower()
    if "charset=" in content_type:
        return response.text
    return response.content


class Fetcher:
    def __init__(self, per_host=2, retries=2, backoff=1.0, respect_robots=False):
        self.per_host = max(1, int(per_host))
        self.respect_robots = respect_robots

        retry = _PoliteRetry(
            total=retries,
            backoff_factor=backoff,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=32, pool_maxsize=32)
        self.session = requests.Session()
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self._lock = threading.Lock()
        self._slots = {}
        self._robots = {}

    def _slot(self, url):
        host = urlsplit(url).netloc.lower()
        with self._lock:
            if host not in self._slots:
                self._slots[host] = threading.BoundedSemaphore(self.per_host)
            return self._slots[host]

    def get(self, url, headers=None, timeout=15):
        """GET a URL; raises requests.RequestException or RobotsDisallowed."""
        headers = headers or {}
        if self.respect_robots and not self.allowed(url, headers.get("User-Agent", "*"), timeout):
            raise RobotsDisallowed(url)
        with self._slot(url):
            response = self.session.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response

    def allowed(self, url, user_agent="*", timeout=10):
        parts = urlsplit(url)
        root = f"{parts.scheme}://{parts.netloc}"
        with self._lock:
            parser = self._robots.get(root)
        if parser is None:
            parser = RobotFileParser(root + "/robots.txt")
            try:
                response = self.session.get(root + "/robots.txt", headers={"User-Agent": user_agent}, timeout=timeout)
                if response.status_code in (401, 403):
                    parser.disallow_all = True
                elif response.status_code >= 400:
                    parser.allow_all = True
                else:
                    parser.parse(response.text.splitlines())
            except requests.RequestException:
                parser.allow_all = True
            with self._lock:
                self._robots[root] = parser
        return parser.can_fetch(user_agent, url)

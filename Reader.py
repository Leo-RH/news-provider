"""The scraping engine.

Loads every connector, crawls their pages concurrently, turns each article
block into an Article, de-duplicates the result and caches it for a short
while so hammering the API doesn't re-scrape the whole internet every call.
"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

from Article import Article
from Connector import Connector

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


class Reader:
    def __init__(self, connector_files, cache_ttl=300, max_workers=8):
        self.connector_files = connector_files
        self.cache_ttl = cache_ttl          # seconds a scrape stays fresh
        self.max_workers = max_workers
        self.connectors = []

        self._articles = []
        self._fetched_at = 0.0

        self.session = requests.Session()
        self.load_connectors()

    # ---- connector loading ---------------------------------------------------

    def load_connectors(self):
        self.connectors = []
        for path in self.connector_files:
            try:
                with open(path, "r", encoding="utf-8") as file:
                    config = json.load(file)
                self.connectors.append(Connector(config))
            except (OSError, ValueError, KeyError) as exc:
                log.warning("Skipping connector %s: %s", path, exc)
        log.info("%d connectors loaded", len(self.connectors))

    # ---- scraping ------------------------------------------------------------

    def _fetch(self, connector, url):
        """Fetch a single URL and return parsed Article objects."""
        try:
            resp = self.session.get(
                url, headers=connector.headers, timeout=connector.timeout
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.warning("Request failed for %s: %s", url, exc)
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        blocks = soup.find_all(
            connector.splitter.html_tag or True,
            class_=connector.splitter.html_class or None,
        ) if not connector.splitter.selector else soup.select(connector.splitter.selector)

        articles = []
        for block in blocks:
            article = self._build_article(connector, block)
            if article and article.is_valid:
                articles.append(article)
            if connector.limit and len(articles) >= connector.limit:
                break
        return articles

    def _build_article(self, connector, block):
        try:
            f = connector.fields
            src = connector.source
            return Article(
                title=f["title"].extract(block, src),
                desc=f["description"].extract(block, src),
                date=f["date"].extract(block, src),
                link=f["link"].extract(block, src),
                topic=f["topic"].extract(block, src),
                image=f["image"].extract(block, src),
                source=connector.source,
                source_name=connector.name,
            )
        except Exception as exc:  # one bad block must never kill the crawl
            log.debug("Failed to parse a block from %s: %s", connector.name, exc)
            return None

    def _scrape_all(self):
        jobs = [(c, url) for c in self.connectors for url in c.urls()]
        collected = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {pool.submit(self._fetch, c, url): url for c, url in jobs}
            for future in as_completed(futures):
                collected.extend(future.result())
        return self._dedup(collected)

    @staticmethod
    def _dedup(articles):
        seen = set()
        unique = []
        for article in articles:
            key = article.dedup_key
            if key in seen:
                continue
            seen.add(key)
            unique.append(article)
        return unique

    # ---- public API ----------------------------------------------------------

    def get_articles(self, force=False):
        """Return cached articles, re-scraping only when the cache is stale."""
        fresh = (time.time() - self._fetched_at) < self.cache_ttl
        if force or not fresh or not self._articles:
            log.info("Scraping %d connectors...", len(self.connectors))
            self._articles = self._scrape_all()
            self._fetched_at = time.time()
            log.info("Collected %d articles", len(self._articles))
        return self._articles

    def sources(self):
        return [
            {"name": c.name, "source": c.source, "paths": c.paths}
            for c in self.connectors
        ]

    def to_JSON(self, force=False):
        payload = {
            "count": 0,
            "fetched_at": self._fetched_at,
            "articles": [a.to_dict() for a in self.get_articles(force=force)],
        }
        payload["count"] = len(payload["articles"])
        return json.dumps(payload, ensure_ascii=False)

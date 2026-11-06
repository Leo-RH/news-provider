"""The scraping engine.

Loads every connector, crawls their pages concurrently, turns each article
block into an Article, de-duplicates and sorts the result (newest first) and
caches it, so hammering the API doesn't re-scrape the whole internet every
call. Optionally a background thread keeps the cache warm, so requests never
wait for a crawl.

Every connector also gets a health record (last status, article count,
errors) so a source that breaks after a site redesign is easy to spot.
"""

import datetime as dt
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

import Formats
from Article import Article
from Connector import Connector
from Dates import to_iso
from Divisor import resolve_url
from Fetcher import Fetcher, RobotsDisallowed

log = logging.getLogger("news_provider")


def _iso_now(timestamp=None):
    moment = dt.datetime.fromtimestamp(timestamp or time.time(), dt.timezone.utc)
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Reader:
    def __init__(self, connector_files, cache_ttl=300, max_workers=8, *, root=None,
                 fetcher=None, per_host=2, respect_robots=False):
        self.connector_files = connector_files
        self.root = root                    # connectors dir, for categories
        self.cache_ttl = cache_ttl          # seconds a scrape stays fresh
        self.max_workers = max_workers
        self.fetcher = fetcher or Fetcher(per_host=per_host, respect_robots=respect_robots)
        self.session = self.fetcher.session
        self.connectors = []
        self.skipped = []                   # connector files that failed to load
        self.health = {}                    # connector origin -> health record

        self._articles = []
        self._fetched_at = 0.0
        self._lock = threading.Lock()       # only one scrape at a time
        self._stop = threading.Event()
        self._refresher = None

        self.load_connectors()

    # ---- connector loading ---------------------------------------------------

    def _category_for(self, path):
        if not self.root:
            return ""
        relative = os.path.relpath(os.path.dirname(os.path.abspath(path)), os.path.abspath(self.root))
        return "" if relative in (".", "") or relative.startswith("..") else relative.replace(os.sep, "/")

    def load_connectors(self):
        self.connectors = []
        self.skipped = []
        for path in self.connector_files:
            try:
                with open(path, "r", encoding="utf-8") as file:
                    config = json.load(file)
                connector = Connector(config, category=self._category_for(path), origin=path)
            except (OSError, ValueError) as exc:
                log.warning("Skipping connector %s: %s", path, exc)
                self.skipped.append({"file": path, "error": str(exc)})
                continue
            for warning in connector.warnings:
                log.warning("Connector %s: %s", path, warning)
            if not connector.enabled:
                continue
            self.connectors.append(connector)
            self.health[path] = {
                "status": "pending", "articles": 0, "errors": [],
                "last_run": None, "last_success": None,
            }
        log.info("%d connectors loaded, %d skipped", len(self.connectors), len(self.skipped))

    # ---- scraping ------------------------------------------------------------

    def _fetch(self, connector, url):
        """Fetch and parse a single URL. Returns (articles, error or None)."""
        try:
            response = self.fetcher.get(url, headers=connector.headers, timeout=connector.timeout)
        except RobotsDisallowed:
            log.warning("robots.txt disallows %s", url)
            return [], "disallowed by robots.txt"
        except requests.RequestException as exc:
            log.warning("Request failed for %s: %s", url, exc)
            return [], f"request failed: {exc}"

        try:
            return self._parse(connector, response), None
        except Exception as exc:
            log.warning("Could not parse %s: %s", url, exc)
            return [], f"parse failed: {exc}"

    def _parse(self, connector, response):
        """Turn a response into Article objects according to the connector type."""
        fields = connector.fields
        now = dt.datetime.now(dt.timezone.utc)

        if connector.type == "rss":
            items = []
            for element, defaults in Formats.feed_entries(response):
                values = {
                    name: rule.extract(element, response.url) if rule.is_active else defaults[name]
                    for name, rule in fields.items()
                }
                values["link"] = resolve_url(values["link"], response.url)
                values["image"] = resolve_url(values["image"], response.url)
                items.append(values)
        else:
            if connector.type == "json":
                elements, base_url = Formats.json_items(response, connector), response.url
            else:
                elements, base_url = Formats.html_blocks(response, connector)
            items = []
            for element in elements:
                try:
                    items.append({name: rule.extract(element, base_url) for name, rule in fields.items()})
                except Exception as exc:  # one bad block must never kill the crawl
                    log.debug("Failed to parse a block from %s: %s", connector.name, exc)

        articles = []
        for values in items:
            # Some cards repeat the headline as their summary; that is not a description.
            if values["description"] == values["title"]:
                values["description"] = ""
            article = Article(
                title=values["title"],
                desc=values["description"],
                date=values["date"],
                link=values["link"],
                topic=values["topic"],
                image=values["image"],
                source=connector.source,
                source_name=connector.name,
                category=connector.category,
                published=to_iso(values["date"], connector.language, connector.timezone, now),
            )
            if article.is_valid:
                articles.append(article)
        return articles

    def _scrape_all(self):
        jobs = [(ci, pi, c, url) for ci, c in enumerate(self.connectors) for pi, url in enumerate(c.urls())]
        results = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {pool.submit(self._fetch, c, url): (ci, pi) for ci, pi, c, url in jobs}
            for future in as_completed(futures):
                results[futures[future]] = future.result()

        finished = time.time()
        collected = []
        for ci, connector in enumerate(self.connectors):
            articles, errors = [], []
            for pi, url in enumerate(connector.urls()):
                page_articles, error = results[(ci, pi)]
                articles.extend(page_articles)
                if error:
                    errors.append(f"{url}: {error}")
            articles = self._dedup(articles)
            if connector.limit:
                articles = articles[:connector.limit]
            self._record_health(connector, articles, errors, finished)
            collected.extend(articles)
        return self._sort(self._dedup(collected))

    def _record_health(self, connector, articles, errors, finished):
        record = self.health.setdefault(connector.origin, {"last_success": None})
        if articles and not errors:
            status = "ok"
        elif articles:
            status = "partial"   # some pages failed
        elif errors:
            status = "error"     # nothing could be fetched / parsed
        else:
            status = "empty"     # pages loaded but the selectors matched nothing
        record.update({"status": status, "articles": len(articles), "errors": errors,
                       "last_run": _iso_now(finished)})
        if articles:
            record["last_success"] = _iso_now(finished)
        if status == "empty":
            log.warning("Connector %s returned no articles; its selectors may be outdated", connector.name)

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

    @staticmethod
    def _sort(articles):
        """Newest first; articles without a known date keep their order at the end."""
        return sorted(articles, key=lambda a: a.published or "", reverse=True)

    # ---- cache ---------------------------------------------------------------

    def _is_fresh(self):
        return (time.time() - self._fetched_at) < self.cache_ttl

    def refresh(self, force=True):
        """Scrape now. Concurrent callers wait for one scrape instead of each running one."""
        seen = self._fetched_at
        with self._lock:
            if self._fetched_at != seen:          # someone refreshed while we waited
                return self._articles
            if not force and self._articles and self._is_fresh():
                return self._articles
            log.info("Scraping %d connectors...", len(self.connectors))
            started = time.time()
            self._articles = self._scrape_all()
            self._fetched_at = time.time()
            log.info("Collected %d articles in %.1fs", len(self._articles), self._fetched_at - started)
            return self._articles

    def get_articles(self, force=False):
        """Return cached articles, re-scraping only when needed.

        With the background refresher running, a stale cache is served as-is
        (the refresher is already replacing it), so requests never block.
        """
        if not force and self._articles and (self._is_fresh() or self.background_running):
            return self._articles
        return self.refresh(force=force)

    @property
    def background_running(self):
        return self._refresher is not None and self._refresher.is_alive()

    def start_background_refresh(self, interval=None):
        """Keep the cache warm from a daemon thread (idempotent)."""
        if self.background_running:
            return
        interval = interval or self.cache_ttl
        self._stop.clear()

        def loop():
            while not self._stop.is_set():
                try:
                    self.refresh(force=True)
                except Exception:
                    log.exception("Background refresh failed")
                self._stop.wait(interval)

        self._refresher = threading.Thread(target=loop, name="news-refresher", daemon=True)
        self._refresher.start()

    def stop_background_refresh(self):
        self._stop.set()

    # ---- public API ----------------------------------------------------------

    @property
    def fetched_at(self):
        return _iso_now(self._fetched_at) if self._fetched_at else None

    def sources(self):
        return [
            {
                "name": c.name,
                "source": c.source,
                "type": c.type,
                "category": c.category,
                "paths": c.paths,
                "health": self.health.get(c.origin, {}),
            }
            for c in self.connectors
        ]

    def health_summary(self):
        statuses = [self.health.get(c.origin, {}).get("status", "pending") for c in self.connectors]
        failing = sum(1 for s in statuses if s in ("error", "empty"))
        return {
            "status": "ok" if failing == 0 else "degraded",
            "connectors": len(self.connectors),
            "failing": failing,
            "partial": statuses.count("partial"),
            "skipped": len(self.skipped),
            "articles": len(self._articles),
            "last_refresh": self.fetched_at,
        }

    def to_JSON(self, force=False):
        articles = [a.to_dict() for a in self.get_articles(force=force)]
        payload = {"count": len(articles), "fetched_at": self.fetched_at, "articles": articles}
        return json.dumps(payload, ensure_ascii=False)

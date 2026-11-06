"""News Provider API.

A tiny Flask service that exposes the scraped articles as JSON so any client
(a website, a Discord/Telegram bot, another script...) can consume them.

Endpoints
    GET /health              -> liveness probe + connector health summary
    GET /sources             -> the connectors currently loaded, with health
    GET /news                -> all articles (JSON), newest first

/news query parameters (all optional, combinable)
    ?source=hacker           substring match on source name or url
    ?category=ai,games       only these categories (connector sub-folders)
    ?topic=vuln              substring match on an article's topic
    ?q=ransomware            full-text search over title + description
    ?since=2026-11-01        only articles published on/after this date
    ?limit=20                cap the number of articles returned
    ?refresh=true            bypass the cache and re-scrape now

Configuration (environment variables)
    CONNECTORS_DIR           folder with connector JSON files (searched recursively)
    CACHE_TTL                seconds a scrape stays fresh (default 300)
    BACKGROUND_REFRESH       keep the cache warm in the background (default true)
    MAX_WORKERS              pages fetched in parallel (default 8)
    PER_HOST_LIMIT           parallel requests to the same site (default 2)
    RESPECT_ROBOTS_TXT       skip URLs disallowed by robots.txt (default false)
    LOG_LEVEL                logging level (default INFO)
"""

import glob
import logging
import os

from flask import Flask, jsonify, request

from Reader import Reader


def _as_bool(value):
    return str(value).lower() in ("1", "true", "yes", "on")


logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(levelname)s %(name)s: %(message)s",
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONNECTORS_DIR = os.environ.get("CONNECTORS_DIR") or os.path.join(BASE_DIR, "connectors")
BACKGROUND_REFRESH = _as_bool(os.environ.get("BACKGROUND_REFRESH", "true"))


def discover_connectors(directory=CONNECTORS_DIR):
    """Find every *.json connector, including those inside category folders."""
    return sorted(glob.glob(os.path.join(directory, "**", "*.json"), recursive=True))


reader = Reader(
    discover_connectors(),
    cache_ttl=int(os.environ.get("CACHE_TTL", 300)),
    max_workers=int(os.environ.get("MAX_WORKERS", 8)),
    root=CONNECTORS_DIR,
    per_host=int(os.environ.get("PER_HOST_LIMIT", 2)),
    respect_robots=_as_bool(os.environ.get("RESPECT_ROBOTS_TXT", "false")),
)
app = Flask(__name__)


@app.before_request
def start_refresher():
    # Started lazily so it only runs in the process that actually serves
    # requests (not in the Flask debug reloader's watcher process).
    if BACKGROUND_REFRESH:
        reader.start_background_refresh()


@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    return response


def _filtered_articles():
    source = request.args.get("source", "").strip().lower()
    categories = {c.strip().lower() for c in request.args.get("category", "").split(",") if c.strip()}
    topic = request.args.get("topic", "").strip().lower()
    query = request.args.get("q", "").strip().lower()
    since = request.args.get("since", "").strip()
    limit = request.args.get("limit", type=int)
    refresh = _as_bool(request.args.get("refresh", ""))

    articles = reader.get_articles(force=refresh)
    result = []
    for a in articles:
        if source and source not in (a.source_name + " " + a.source).lower():
            continue
        if categories and (a.category or "").lower() not in categories:
            continue
        if topic and topic not in (a.topic or "").lower():
            continue
        if query and query not in (a.title + " " + a.desc).lower():
            continue
        # ISO 8601 strings compare correctly as plain text.
        if since and (not a.published or a.published < since):
            continue
        result.append(a.to_dict())

    if limit and limit > 0:
        result = result[:limit]
    return result


@app.route("/health", methods=["GET"])
def health():
    return jsonify(reader.health_summary())


@app.route("/sources", methods=["GET"])
def sources():
    return jsonify({"sources": reader.sources(), "skipped": reader.skipped})


@app.route("/news", methods=["GET"])
def get_news():
    articles = _filtered_articles()
    return jsonify({"count": len(articles), "fetched_at": reader.fetched_at, "articles": articles})


if __name__ == "__main__":
    app.run(debug=True)

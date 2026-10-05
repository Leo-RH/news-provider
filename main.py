"""News Provider API.

A tiny Flask service that exposes the scraped articles as JSON so any client
(a website, a Discord/Telegram bot, another script...) can consume them.

Endpoints
    GET /health              -> liveness probe
    GET /sources             -> the connectors currently loaded
    GET /news                -> all articles (JSON)

/news query parameters (all optional, combinable)
    ?source=hacker           substring match on source name or url
    ?topic=vuln              substring match on an article's topic
    ?q=ransomware            full-text search over title + description
    ?limit=20                cap the number of articles returned
    ?refresh=true            bypass the cache and re-scrape now
"""

import json
import logging

from flask import Flask, jsonify, request

from Reader import Reader

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def import_providers(path="providers.json"):
    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)
    return [p["file"] for p in data.get("providers", [])]


reader = Reader(import_providers())
app = Flask(__name__)


@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    return response


def _as_bool(value):
    return str(value).lower() in ("1", "true", "yes", "on")


def _filtered_articles():
    source = request.args.get("source", "").strip().lower()
    topic = request.args.get("topic", "").strip().lower()
    query = request.args.get("q", "").strip().lower()
    limit = request.args.get("limit", type=int)
    refresh = _as_bool(request.args.get("refresh", ""))

    articles = reader.get_articles(force=refresh)
    result = []
    for a in articles:
        if source and source not in (a.source_name + " " + a.source).lower():
            continue
        if topic and topic not in (a.topic or "").lower():
            continue
        if query and query not in (a.title + " " + a.desc).lower():
            continue
        result.append(a.to_dict())

    if limit and limit > 0:
        result = result[:limit]
    return result


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "connectors": len(reader.connectors)})


@app.route("/sources", methods=["GET"])
def sources():
    return jsonify({"sources": reader.sources()})


@app.route("/news", methods=["GET"])
def get_news():
    articles = _filtered_articles()
    return jsonify({"count": len(articles), "articles": articles})


if __name__ == "__main__":
    app.run(debug=True)

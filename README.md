# News Provider

A lightweight, JSON-driven news aggregation engine. It crawls any number of news
websites and serves everything as a single, unified JSON feed through a small
HTTP API — ready to power a website, a Discord/Telegram bot, or any script.

Each site is described by a **connector**: a plain JSON file of scraping rules.
Adding a new source never requires writing code.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Flask](https://img.shields.io/badge/api-flask-000000)
![License](https://img.shields.io/badge/license-MIT-green)

## Features

- **Code-free connectors** — describe any site with CSS selectors, attribute
  selection, regex and small transforms, all in JSON.
- **Three source types** — scrape **HTML** pages, read **RSS/Atom** feeds
  (no selectors needed), or pull articles out of **JSON** (APIs, or data
  embedded in JavaScript-rendered pages such as `__NEXT_DATA__` / JSON-LD).
- **Handles messy sites** — lazy-loaded and placeholder images, pages without
  a wrapper per article, cards that are a bare link, missing charsets,
  Windows-1252 leftovers, icon-font junk in text.
- **Unified JSON API** — one endpoint returns articles from every source,
  **newest first**, with a normalised ISO 8601 `published` date (English,
  Portuguese and many other languages, including "2 hours ago").
- **Categories** — put connectors in sub-folders (`games/`, `ai/`...) and
  filter with `?category=`.
- **Fast & polite** — pages are crawled concurrently, at most a couple of
  requests per site at once, with retries and backoff on transient errors.
- **Always warm** — a background thread refreshes the cache, so API calls
  never wait for a crawl.
- **Observable** — per-connector health (`ok`, `partial`, `empty`, `error`)
  shows at a glance which source broke after a site redesign.
- **Safe to edit** — connector files are validated on load; a typo or a broken
  selector is reported with the file name instead of silently returning nothing.
- **Deployable** — run it with Python or a single `docker run`.

## Quick start

### With Python

```bash
pip install -r requirements.txt
python main.py
```

The API starts on `http://127.0.0.1:5000`.

### With Docker

```bash
docker build -t news-provider .
docker run -p 5000:5000 news-provider
```

The API is then available on `http://localhost:5000`. Inside the container it is
served by [waitress](https://docs.pylonsproject.org/projects/waitress/) (a
production WSGI server). Change the port with `-e PORT=8080`.

> The engine starts with **no sources**. Add connectors to make it return
> articles — see [Adding a source](#adding-a-source). Ready-made connectors for
> dozens of sites live in
> [awesome_news_provider_connectors](https://github.com/Leo-RH/awesome_news_provider_connectors).

## API

| Endpoint       | Description                                               |
|----------------|-----------------------------------------------------------|
| `GET /health`  | Liveness probe + summary (`ok`/`degraded`, failing connectors, last refresh). |
| `GET /sources` | The connectors currently loaded, each with its health record. Files that failed validation are listed under `skipped`. |
| `GET /news`    | All articles as JSON, newest first.                       |

`/news` query parameters (combinable):

| Param      | Example              | Effect |
|------------|----------------------|--------|
| `source`   | `?source=hacker`     | Only sources whose name/url contains the text. |
| `category` | `?category=ai,games` | Only these categories (comma-separated). |
| `topic`    | `?topic=vuln`        | Only articles whose topic contains the text. |
| `q`        | `?q=ransomware`      | Full-text search over title + description. |
| `since`    | `?since=2026-11-01`  | Only articles published on or after this date/time. |
| `limit`    | `?limit=20`          | Cap the number of articles returned. |
| `refresh`  | `?refresh=true`      | Bypass the cache and re-scrape now. |

Example response:

```json
{
  "count": 1,
  "fetched_at": "2026-11-06T18:00:00Z",
  "articles": [
    {
      "title": "Example headline",
      "description": "Short summary of the article.",
      "date": "2 hours ago",
      "published": "2026-11-06T16:00:00Z",
      "link": "https://example.com/article",
      "topic": "Security",
      "image": "https://example.com/image.jpg",
      "category": "cybersecurity",
      "source": "https://example.com",
      "source_name": "Example News"
    }
  ]
}
```

`date` is the text exactly as the site shows it; `published` is the same moment
normalised to ISO 8601 UTC (empty when the site gives no date). `category` is
the connector's sub-folder (or its `"category"` key).

## Configuration

All settings are optional environment variables.

| Variable             | Default        | Meaning |
|----------------------|----------------|---------|
| `CONNECTORS_DIR`     | `./connectors` | Folder with connector JSON files, searched recursively. |
| `CACHE_TTL`          | `300`          | Seconds a scrape stays fresh (also the background refresh interval). |
| `BACKGROUND_REFRESH` | `true`         | Keep the cache warm from a background thread. |
| `MAX_WORKERS`        | `8`            | Pages fetched in parallel. |
| `PER_HOST_LIMIT`     | `2`            | Parallel requests to the same site. |
| `RESPECT_ROBOTS_TXT` | `false`        | Skip URLs that the site's robots.txt disallows. |
| `LOG_LEVEL`          | `INFO`         | Logging verbosity. |

## Adding a source

1. Create a connector JSON file (full guide in **[CONNECTORS.md](CONNECTORS.md)**).
2. Drop it into the `connectors/` directory — optionally inside a category
   sub-folder such as `connectors/games/`.
3. Restart the API — it auto-loads every `*.json` it finds.

No registration or code changes required. Check `GET /sources` to confirm the
connector loaded and is returning articles.

## Project layout

```
.
├── main.py            # Flask API: endpoints, filtering, CORS, configuration
├── Reader.py          # Engine: crawl, parse, de-dup, sort, cache, health
├── Fetcher.py         # HTTP: shared session, retries, per-site limits, robots.txt
├── Formats.py         # HTML blocks, RSS/Atom entries and JSON items
├── Connector.py       # Builds and validates a source from one JSON file
├── Splitter.py        # Cuts a page into article blocks
├── Divisor.py         # A single field-extraction rule
├── Dates.py           # Free-form dates -> ISO 8601
├── Article.py         # Article model + JSON shape
├── connectors/        # Your connector JSON files live here
├── tests/             # Offline test suite
├── html_test/         # Optional browser UI for eyeballing the feed
├── Dockerfile
├── requirements.txt
├── CONNECTORS.md      # How to write a connector
└── README.md
```

### Tests

```bash
python -m unittest discover tests
```

The suite runs fully offline against small inline fixtures.

### Optional test UI

With the API running, open `html_test/index.html` in a browser to see the feed
rendered as cards with working links and images.

## License

[MIT](LICENSE)

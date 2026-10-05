# News Provider

A small, JSON-driven news aggregation engine. It crawls any number of news
sites and serves everything as one JSON feed through a tiny HTTP API, so the
same data can power a website, a Discord/Telegram bot, or any script.

Each site is described by a **connector** — a plain JSON file of scraping rules.
Anyone can add a new source without touching Python. See
[`CONNECTORS.md`](CONNECTORS.md) for the full authoring guide.

## How it works

```
providers.json ──▶ Reader ──▶ Connectors (JSON rules)
                     │
                     ├─ fetch every page (concurrently, with the OS trust store)
                     ├─ split each page into article blocks
                     ├─ extract fields (title, link, image, …)
                     ├─ de-duplicate + cache (5 min)
                     ▼
                  Flask API  ──▶  JSON
```

| File            | Role |
|-----------------|------|
| `main.py`       | Flask API (endpoints, filtering, CORS). |
| `Reader.py`     | The engine: fetch, parse, dedup, cache. |
| `Connector.py`  | Turns one JSON file into a source definition. |
| `Divisor.py`    | A single field-extraction rule (selector + attribute + regex). |
| `Article.py`    | One article (and its JSON shape). |
| `providers.json`| The list of active connectors. |
| `html_test/`    | A throwaway web UI for eyeballing the feed. |

## Running it

```bash
pip install -r requirements.txt
python main.py
```

The API starts on `http://127.0.0.1:5000`.

> On this machine the interpreter is the Microsoft Store build, invoked as
> `python3.13` (plain `python` opens the Store). Use `python3.13 main.py`.

### Endpoints

| Endpoint    | Description |
|-------------|-------------|
| `GET /health`  | Liveness + number of connectors loaded. |
| `GET /sources` | The connectors currently active. |
| `GET /news`    | All articles as JSON. |

`/news` query parameters (combinable):

| Param      | Example            | Effect |
|------------|--------------------|--------|
| `source`   | `?source=hacker`   | Only sources whose name/url contains the text. |
| `topic`    | `?topic=vuln`      | Only articles whose topic contains the text. |
| `q`        | `?q=ransomware`    | Full-text search over title + description. |
| `limit`    | `?limit=20`        | Cap the number of articles. |
| `refresh`  | `?refresh=true`    | Bypass the cache and re-scrape now. |

Response shape:

```json
{
  "count": 2,
  "articles": [
    {
      "title": "…", "description": "…", "date": "…",
      "link": "https://…", "topic": "…", "image": "https://…",
      "source": "https://thehackernews.com", "source_name": "The Hacker News"
    }
  ]
}
```

### With Docker

```bash
docker build -t news-provider .
docker run -p 5000:5000 news-provider
```

The API is then on `http://localhost:5000`. Inside the container it is served by
[waitress](https://docs.pylonsproject.org/projects/waitress/) (a real WSGI
server), not the Flask dev server. Override the port with `-e PORT=8080`.

### The test UI

Open `html_test/index.html` in a browser while the API runs. It fetches
`/news` and renders cards with working links and images.

## Adding a source

1. Write a connector JSON (see [`CONNECTORS.md`](CONNECTORS.md)).
2. Register it in `providers.json`.
3. Restart the API.

## What changed / why it's better

- **Links and images are now real URLs.** The old engine read the *text* of
  `<a>`/`<img>` tags; it now reads `href`/`src` and resolves relative URLs.
- **Far more customizable connectors** — CSS selectors, attribute selection
  (incl. lazy-load fallbacks), and regex, all from JSON.
- **Concurrent crawling** with a shared session, real timeouts and a
  browser `User-Agent` (fewer blocks, much faster).
- **Response caching** (5 min TTL) so `/news` doesn't re-scrape every call.
- **De-duplication** across pages and sources.
- **Robust**: a missing field or a failed page no longer kills the request;
  problems are logged instead of silently swallowed.
- **Richer API**: `/sources`, `/health`, and filtering by source/topic/query.
- **TLS that works behind antivirus/proxy inspection** via the OS trust store.

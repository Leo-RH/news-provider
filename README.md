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
  selection and regex, all in JSON.
- **Unified JSON API** — one endpoint returns articles from every source.
- **Fast** — pages are crawled concurrently with a shared HTTP session.
- **Efficient** — responses are cached (configurable TTL) and de-duplicated.
- **Resilient** — a broken selector or an unreachable page is logged, never
  crashes the request.
- **Filterable** — query by source, topic, or free-text search.
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
> articles — see [Adding a source](#adding-a-source).

## API

| Endpoint       | Description                              |
|----------------|------------------------------------------|
| `GET /health`  | Liveness probe + number of connectors.   |
| `GET /sources` | The connectors currently loaded.         |
| `GET /news`    | All articles as JSON.                     |

`/news` query parameters (combinable):

| Param     | Example           | Effect |
|-----------|-------------------|--------|
| `source`  | `?source=hacker`  | Only sources whose name/url contains the text. |
| `topic`   | `?topic=vuln`     | Only articles whose topic contains the text. |
| `q`       | `?q=ransomware`   | Full-text search over title + description. |
| `limit`   | `?limit=20`       | Cap the number of articles returned. |
| `refresh` | `?refresh=true`   | Bypass the cache and re-scrape now. |

Example response:

```json
{
  "count": 1,
  "articles": [
    {
      "title": "Example headline",
      "description": "Short summary of the article.",
      "date": "Oct 05, 2026",
      "link": "https://example.com/article",
      "topic": "Security",
      "image": "https://example.com/image.jpg",
      "source": "https://example.com",
      "source_name": "Example News"
    }
  ]
}
```

## Adding a source

1. Create a connector JSON file (full guide in **[CONNECTORS.md](CONNECTORS.md)**).
2. Drop it into the `connectors/` directory.
3. Restart the API — it auto-loads every `*.json` in that folder.

No registration or code changes required. Point the engine at a different folder
with the `CONNECTORS_DIR` environment variable.

## Project layout

```
.
├── main.py            # Flask API: endpoints, filtering, CORS
├── Reader.py          # Engine: fetch, parse, de-dup, cache
├── Connector.py       # Builds a source definition from one JSON file
├── Divisor.py         # A single field-extraction rule
├── Article.py         # Article model + JSON shape
├── connectors/        # Your connector JSON files live here
├── html_test/         # Optional browser UI for eyeballing the feed
├── Dockerfile
├── requirements.txt
├── CONNECTORS.md      # How to write a connector
└── README.md
```

### Optional test UI

With the API running, open `html_test/index.html` in a browser to see the feed
rendered as cards with working links and images.

## License

[MIT](LICENSE)

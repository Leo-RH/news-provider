# Writing a Connector

A **connector** is a single JSON file that teaches the engine how to read one
website. You never touch Python — you only describe *where* the news is and
*how* to pull each piece out of the page. Drop the file into the `connectors/`
directory, restart the API, and it works.

---

## The mental model

Every news page is a list of repeating blocks (one per article). The engine:

1. **Fetches** each page under `source` + `paths`.
2. **Splits** the page into article blocks using `splitter`.
3. For each block, **extracts** the fields in `patterns` (title, link, image…).

So a connector only has to answer two questions:
*"What does one article block look like?"* (`splitter`) and
*"Where is each field inside that block?"* (`patterns`).

---

## Minimal example

```json
{
  "name": "The Hacker News",
  "source": "https://thehackernews.com",
  "paths": ["/"],
  "splitter": { "selector": "div.body-post.clear" },
  "patterns": {
    "title":       { "selector": "h2.home-title" },
    "description": { "selector": "div.home-desc" },
    "date":        { "selector": "span.h-datetime" },
    "link":        { "selector": "a.story-link", "attribute": "href" },
    "topic":       { "selector": "span.h-tags" },
    "image":       { "selector": "img.home-img-src", "attribute": ["data-src", "src"] }
  }
}
```

---

## Top-level keys

| Key        | Required | Meaning |
|------------|----------|---------|
| `name`     | no       | Friendly name shown in the API (`source_name`). Defaults to `source`. |
| `source`   | **yes**  | Base URL of the site, e.g. `https://thehackernews.com`. |
| `paths`    | no       | List of pages to crawl, relative to `source` (or full URLs). Default `["/"]`. |
| `limit`    | no       | Max articles to keep from this source. |
| `request`  | no       | `{ "timeout": 15, "headers": { ... } }` — override the HTTP timeout or add headers (e.g. a custom `User-Agent`). |
| `splitter` | **yes**  | How to find one article block. A [selector object](#selector-objects). |
| `patterns` | **yes**  | One [selector object](#selector-objects) per field. |

Recognised fields in `patterns`: `title`, `description`, `date`, `link`,
`topic`, `image`. Any field you omit is simply left empty — the article is
still returned as long as it has at least a title *or* a link.

---

## Selector objects

A selector object tells the engine how to locate an element and what to read
from it. Every key is optional; use whichever is convenient.

| Key          | What it does |
|--------------|--------------|
| `selector`   | A **CSS selector** — the recommended way. E.g. `"div.content-image img"`, `"a.story-link"`, `"article.post > h2"`. |
| `html_tag` / `html_class` | The older, simpler way: pick by tag name + single class. `{ "html_tag": "h3", "html_class": "title" }`. Use `selector` instead when you can. |
| `attribute`  | Which attribute to read instead of the text. E.g. `"href"`, `"src"`, `"data-src"`, `"content"`. Use `"text"` (the default for most fields) to read the inner text. Can be a **list** to try several in order — great for lazy-loaded images: `["data-src", "srcset", "src"]`. |
| `regex`      | A regular expression applied to the extracted value. If it has a capturing group, group 1 is kept; otherwise the whole match. Handy for cleaning dates or IDs. |
| `resolve`    | `true`/`false`. Turn a relative URL (`/post/123`) into an absolute one using `source`. Already **on by default** for `link` and `image`. |

### Smart defaults

You rarely need `attribute` because each field defaults sensibly:

| Field       | Default reads | Relative URLs resolved? |
|-------------|---------------|-------------------------|
| title, description, date, topic | inner **text** | no |
| link        | the `href` attribute | **yes** |
| image       | first of `data-src`, `data-lazy-src`, `src`, `srcset` | **yes** |

So a `link` field only needs `{ "selector": "a.story-link" }` — it grabs the
`href` and makes it absolute for you.

---

## CSS selector cheat sheet

| Pattern            | Matches |
|--------------------|---------|
| `div.card`         | `<div class="card">` |
| `div.a.b`          | element with **both** classes `a` and `b` |
| `a.story-link`     | `<a class="story-link">` |
| `.content img`     | any `<img>` inside something with class `content` |
| `div > h2`         | an `<h2>` that is a **direct** child of a `<div>` |
| `article[data-id]` | `<article>` that has a `data-id` attribute |

Tip: open the site in your browser, right-click the element → *Inspect*, then
right-click the node → *Copy → Copy selector* for a starting point.

---

## Installing the connector

Save your JSON file in the `connectors/` directory — any file name ending in
`.json` is picked up automatically. There is no registry to edit.

```
connectors/
└── myNewConnector.json
```

Restart the API (`python main.py`). Check it loaded at
`http://127.0.0.1:5000/sources`, then see its articles at
`http://127.0.0.1:5000/news?source=mynew`.

> Want the connectors to live elsewhere? Point the engine at another folder with
> the `CONNECTORS_DIR` environment variable.

---

## Testing & troubleshooting

- **No articles?** Your `splitter` probably matches nothing. Loosen it (fewer
  classes) until blocks appear, then tighten the field selectors.
- **Empty title/link?** The selector is relative to the *block*, not the page.
  Make sure the element really lives inside each article block.
- **Images blank?** The site lazy-loads them. Add the real attribute to the
  list: `"attribute": ["data-src", "data-lazy-src", "srcset", "src"]`.
- **Links are `/foo` not `https://site/foo`?** Nothing to do — `link` and
  `image` are resolved automatically. For another field add `"resolve": true`.
- **403 / blocked?** Add a browser-like `User-Agent` under `request.headers`.

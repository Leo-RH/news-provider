# Writing a Connector

A **connector** is a single JSON file that teaches the engine how to read one
website. You never touch Python — you only describe *where* the news is and
*how* to pull each piece out of the page. Drop the file into the `connectors/`
directory, restart the API, and it works.

There are three kinds of connector:

| `type`   | Use it when | Needs |
|----------|-------------|-------|
| `html` (default) | The site lists articles in its HTML. | `splitter` + `patterns` |
| `rss`    | The site publishes an RSS or Atom feed. The most robust option: feeds don't break when a site is redesigned. | Just the feed URL |
| `json`   | The articles come from a JSON API, or are embedded as JSON in a JavaScript-rendered page (`__NEXT_DATA__`, JSON-LD...). | `json` + `patterns` with `path` |

---

## The mental model (html)

Every news page is a list of repeating blocks (one per article). The engine:

1. **Fetches** each page under `source` + `paths`.
2. **Splits** the page into article blocks using `splitter`.
3. For each block, **extracts** the fields in `patterns` (title, link, image…).

So a connector only has to answer two questions:
*"What does one article block look like?"* (`splitter`) and
*"Where is each field inside that block?"* (`patterns`).

---

## Minimal examples

**HTML**

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
    "link":        { "selector": "a.story-link" },
    "topic":       { "selector": "span.h-tags" },
    "image":       { "selector": "img.home-img-src" }
  }
}
```

**RSS / Atom** — title, link, date, description, topics and image are read
from the feed automatically:

```json
{
  "name": "Ars Technica - Security",
  "source": "https://arstechnica.com",
  "type": "rss",
  "paths": ["/security/feed/"]
}
```

**JSON** — articles embedded in a Next.js page:

```json
{
  "name": "Example",
  "source": "https://example.com",
  "type": "json",
  "paths": ["/news"],
  "json": { "script": "script#__NEXT_DATA__", "items": "props.pageProps.posts" },
  "patterns": {
    "title": { "path": "title" },
    "date":  { "path": "publishedAt" },
    "link":  { "path": "slug", "format": "/news/{}" },
    "image": { "path": ["cover.url", "thumbnail"] }
  }
}
```

---

## Top-level keys

| Key        | Required | Meaning |
|------------|----------|---------|
| `name`     | no       | Friendly name shown in the API (`source_name`). Defaults to `source`. |
| `source`   | **yes**  | Base URL of the site, e.g. `https://thehackernews.com`. |
| `type`     | no       | `html` (default), `rss` or `json`. |
| `paths`    | no       | Pages (or feeds) to crawl, relative to `source` or full URLs. Default `["/"]`. |
| `limit`    | no       | Max articles kept from this connector, across all its paths. |
| `language` | no       | Language(s) of the site's dates, e.g. `"pt"` or `["pt", "en"]`. Default `"en"`. Used to read dates like "Há 2 horas". |
| `timezone` | no       | IANA time zone for dates that don't state one, e.g. `"America/Sao_Paulo"`. Default `"UTC"`. |
| `category` | no       | Category of the articles. Defaults to the connector's sub-folder name. |
| `parser`   | no       | HTML parser: `lxml` (default, fast) or `html.parser` (more forgiving with some invalid HTML — see [troubleshooting](#testing--troubleshooting)). |
| `request`  | no       | `{ "timeout": 15, "headers": { ... } }` — override the HTTP timeout or add headers. |
| `enabled`  | no       | `false` keeps the file but doesn't load it. |
| `splitter` | html     | How to find one article block. See [splitter](#splitter). |
| `patterns` | html, json | One [field rule](#field-rules) per field. Optional for `rss` (overrides the defaults). |
| `json`     | json     | Where the JSON items are. See [json connectors](#json-connectors). |

Recognised fields in `patterns`: `title`, `description`, `date`, `link`,
`topic`, `image`. Any field you omit is simply left empty — the article is
still returned as long as it has at least a title *or* a link.

Unknown keys (typos such as `"pattern"`) are reported as warnings in the log,
and an invalid CSS selector or regex stops the connector from loading with a
clear message — check the log or `GET /sources` (`skipped`).

---

## Splitter

| Key             | What it does |
|-----------------|--------------|
| `selector`      | CSS selector matching one block per article. A list of selectors combines their matches, in page order. |
| `group`         | `"siblings"` — for pages with **no wrapper per article**. Each match starts a block that also contains the elements after it, up to the next match. E.g. a headline followed by its summary and "read more" link. |
| `exclude`       | CSS selector (or list). Blocks that match it, or contain a match, are skipped — ads, sponsored cards, non-news cards. |
| `exclude_regex` | Regex. Blocks whose text matches it are skipped, e.g. `"Presented by "`. |
| `html_tag` / `html_class` | Legacy alternative to `selector`. |

```json
"splitter": { "selector": "h2.Headline", "group": "siblings" }
```

---

## Field rules

A field rule tells the engine how to locate an element inside a block and
what to read from it. Every key is optional; use whichever is convenient.

| Key          | What it does |
|--------------|--------------|
| `selector`   | A **CSS selector**. A **list** is a priority order: the first selector that yields a value wins (unlike a comma-separated selector, which just takes whatever comes first on the page). `":self"` means the block itself — use it when the whole card *is* the `<a>` link. |
| `path`       | For `json` connectors: a dotted path inside an item, e.g. `"image.url"`, `"tags.*.name"`. A list = fallbacks. |
| `attribute`  | Which attribute to read instead of the text: `"href"`, `"src"`, `"datetime"`, `"content"`... `"text"` reads the inner text. A **list** tries several in order. |
| `transform`  | Post-processing, a name or a list applied in order: `base64` (decode), `lower`, `upper`, `strip_query` (drop `?…` from a URL). |
| `regex`      | Regular expression applied to the value. With a capturing group, group 1 is kept; otherwise the whole match. If it doesn't match, the field is empty. |
| `format`     | Template the value is put into; `{}` marks the spot. E.g. `"/blog/{}"` turns a slug into a path (then resolved to a full URL for `link`/`image`). |
| `multiple`   | `true` collects **every** match (de-duplicated) instead of the first, joined with `separator` (default `", "`). Handy for topics/tags. |
| `resolve`    | `true`/`false`. Turn a relative URL into an absolute one (relative to the page it was found on). On by default for `link` and `image`. |
| `html_tag` / `html_class` | Legacy alternative to `selector`. |

Processing order: find → read attribute/text → clean whitespace → `transform`
→ `regex` → `format` → resolve URL.

If the first element a selector finds is empty (e.g. an image-only link before
the real headline link), the next match is tried automatically.

### Smart defaults

You rarely need `attribute` because each field defaults sensibly:

| Field       | Default reads | Relative URLs resolved? |
|-------------|---------------|-------------------------|
| title, description, date, topic | inner **text** | no |
| link        | the `href` attribute | **yes** |
| image       | the first real URL among `data-src`, `data-lazy-src`, `data-original`, `data-src-img`, `src`, `data-srcset`, `data-lazy-srcset`, `srcset` | **yes** |

For images the engine also:

- skips `data:` placeholders (the 1×1 pixel lazy-loading sites put in `src`)
  and moves on to the next attribute;
- picks the **largest** candidate of a `srcset`;
- looks inside the element when the selector points at a `<picture>`,
  `<figure>` or wrapper instead of the `<img>`.

So `"image": { "selector": "figure img" }` is usually all you need. Only list
attributes when the site uses an unusual one — and then remember that only
those attributes are tried.

### Text cleanup

Text is read with spaces between inline tags ("a 2021 **essay** and" stays
readable), whitespace is collapsed, and invisible characters (zero-width
spaces, icon-font glyphs, Windows-1252 leftovers like `&#151;`) are fixed or
removed. A description identical to the title is dropped.

### Dates

`date` is returned exactly as the site prints it. The engine also fills a
`published` field with the same moment in ISO 8601 UTC, understanding ISO
dates, RSS dates, "Nov. 6, 2026", "2 hours ago", "Há 1 hora",
"6 de novembro de 2026"... Set `language` (and `timezone` for sites that print
local times) so it reads the site's dates correctly. Articles are sorted by
`published`, newest first.

When the date lives in an attribute, read it: `{ "selector": "time", "attribute": "datetime" }`.
When it's encoded, decode it: `{ "selector": "span.date", "attribute": "data-ts", "transform": "base64" }`.

---

## RSS / Atom connectors

```json
{ "name": "Phoronix", "source": "https://www.phoronix.com", "type": "rss", "paths": ["/rss.php"] }
```

Every field has a built-in default:

| Field       | Read from |
|-------------|-----------|
| title       | `<title>` (HTML stripped) |
| link        | `<link>` (RSS) / `<link rel="alternate" href>` (Atom) / FeedBurner's original link / a permalink `<guid>` |
| date        | `<pubDate>`, `<published>`, `<updated>`, `<dc:date>` |
| description | `<description>` / `<summary>`, or the full `<content:encoded>`, as plain text (max 500 characters) |
| topic       | the first 5 `<category>` / `<dc:subject>` values |
| image       | `media:thumbnail`, `media:content`, an image `<enclosure>`, `itunes:image`, or the first `<img>` in the post |

To find a site's feed, look for `<link rel="alternate" type="application/rss+xml">`
in its HTML, or try `/feed/`, `/rss.xml`, `/feed.xml`. You can still override
any field with a normal field rule in `patterns`.

---

## JSON connectors

```json
"json": {
  "script": "script[type='application/ld+json']",
  "items":  "itemListElement.*.item",
  "match":  { "@type": ["NewsArticle", "Article"] }
}
```

| Key      | Meaning |
|----------|---------|
| `script` | CSS selector of `<script>` tags holding the JSON inside an HTML page. Omit it when the URL itself returns JSON (an API). Every matching script is parsed. |
| `items`  | Dotted path to the list of articles. `*` walks into every element of a list/object. Omit it if the document itself is the list. |
| `match`  | Keep only items whose keys equal these values (a list = any of them). |

Fields then use `path` instead of `selector`. A value that is an object is
read via its `url`, `href`, `src`, `name` or `text` key (so a JSON-LD
`ImageObject` just works); a list gives one value per element (use `multiple`).

---

## CSS selector cheat sheet

| Pattern            | Matches |
|--------------------|---------|
| `div.card`         | `<div class="card">` |
| `div.a.b`          | element with **both** classes `a` and `b` |
| `a.story-link`     | `<a class="story-link">` |
| `.content img`     | any `<img>` inside something with class `content` |
| `div > h2`         | an `<h2>` that is a **direct** child of a `<div>` |
| `h2 + p`           | the `<p>` right after an `<h2>` |
| `article[data-id]` | `<article>` that has a `data-id` attribute |
| `div[class^=_card_]` | class attribute *starting* with `_card_` — useful when sites add random hashes (`_card_1ptpv_1`) |
| `div[class*=Title]` | class attribute *containing* `Title` |
| `article:has(h3 a)` | `<article>` elements that contain an `<h3>` with a link |
| `a:not(.ad)`       | links without the class `ad` |
| `a:-soup-contains('Full Story')` | links whose text contains "Full Story" |

Tip: open the site in your browser, right-click the element → *Inspect*, then
right-click the node → *Copy → Copy selector* for a starting point. Prefer
stable class names over generated ones.

---

## Installing the connector

Save your JSON file in the `connectors/` directory — any file name ending in
`.json` is picked up automatically, including files in sub-folders. The
sub-folder name becomes the articles' `category`:

```
connectors/
├── games/
│   └── ignConnector.json        -> category "games"
└── myNewConnector.json          -> no category
```

Restart the API (`python main.py`). Check it loaded at
`http://127.0.0.1:5000/sources`, then see its articles at
`http://127.0.0.1:5000/news?source=mynew`.

> Want the connectors to live elsewhere? Point the engine at another folder with
> the `CONNECTORS_DIR` environment variable.

---

## Testing & troubleshooting

`GET /sources` shows each connector's health after a crawl:

| status    | Meaning |
|-----------|---------|
| `ok`      | Articles found, every page loaded. |
| `partial` | Articles found, but some pages failed (see `errors`). |
| `empty`   | Pages loaded but the splitter matched nothing — the site probably changed its HTML. |
| `error`   | No page could be fetched or parsed (see `errors`). |

- **No articles (`empty`)?** Your `splitter` probably matches nothing. Loosen it
  (fewer classes) until blocks appear, then tighten the field selectors.
- **Empty title/link?** The selector is relative to the *block*, not the page.
  If the block itself is the `<a>`, use `"selector": ":self"` for the link.
- **One article = several elements with no common wrapper?** Use
  `"group": "siblings"` on the splitter.
- **A field is empty only with the default parser?** Some pages contain invalid
  HTML (a `<p>` inside an `<h2>`, nested `<p>`s) that `lxml` repairs
  differently. Add `"parser": "html.parser"`.
- **Images blank?** The site lazy-loads them in an unusual attribute. Add it to
  `attribute` (together with `src`): `["data-lazy", "src"]`.
- **The articles are not in the HTML at all?** The page is rendered by
  JavaScript. Look for an RSS feed (`type: rss`) or for the data in a
  `<script>` tag (`type: json`).
- **Wrong `published` dates?** Set `language` and `timezone`.
- **403 / blocked?** The site refuses automated access. Look for its official
  RSS feed; if that is blocked too, leave the site out.

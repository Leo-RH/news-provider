(function () {
  "use strict";

  var ENDPOINT = "http://127.0.0.1:5000/news";
  var PREVIEW_LENGTH = 160; // chars of description shown on the pill

  var feedEl = document.getElementById("feed");
  var statusEl = document.getElementById("status");
  var modalEl = document.getElementById("modal");

  // ---- Helpers -------------------------------------------------------------

  // Treat a value as a usable URL only if it looks like one. The backend
  // currently returns plain text for `image` (and `link`); this keeps things
  // graceful now and "just works" once real URLs are returned.
  function isUrl(value) {
    return typeof value === "string" && /^(https?:\/\/|data:image\/)/i.test(value.trim());
  }

  function truncate(text) {
    var t = (text || "").trim();
    if (t.length <= PREVIEW_LENGTH) return t;
    var slice = t.slice(0, PREVIEW_LENGTH);
    var lastSpace = slice.lastIndexOf(" ");
    if (lastSpace > 0) slice = slice.slice(0, lastSpace);
    return slice.replace(/[.,;:\-\s]+$/, "") + "....";
  }

  // Build an image node, or a placeholder if the source isn't a valid URL yet.
  function buildImage(src, alt, imgClass) {
    if (isUrl(src)) {
      var img = document.createElement("img");
      img.className = imgClass;
      img.src = src.trim();
      img.alt = alt || "";
      img.loading = "lazy";
      img.addEventListener("error", function () {
        img.replaceWith(buildPlaceholder());
      });
      return img;
    }
    return buildPlaceholder();
  }

  // Category (connector folder) and topic badges, shared by pill and modal.
  function buildTags(article) {
    var tags = document.createElement("div");
    tags.className = "pill__tags";
    if (article.category) {
      var category = document.createElement("span");
      category.className = "pill__category";
      category.textContent = article.category;
      tags.appendChild(category);
    }
    if (article.topic) {
      var topic = document.createElement("span");
      topic.className = "pill__topic";
      topic.textContent = article.topic;
      tags.appendChild(topic);
    }
    return tags;
  }

  // `published` is ISO 8601 UTC; show it in the reader's locale. A value at
  // exactly midnight UTC means the site only gave a day, so show just the day
  // (in UTC, or it would slip to the previous day west of Greenwich). Falls
  // back to the raw `date` text when the engine couldn't parse it.
  function formatPublished(article) {
    if (!article.published) return article.date || "";
    var when = new Date(article.published);
    if (isNaN(when.getTime())) return article.date || "";
    if (/T00:00:00Z$/.test(article.published)) {
      return when.toLocaleDateString(undefined, { dateStyle: "medium", timeZone: "UTC" });
    }
    return when.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  }

  function fillDate(el, article) {
    var text = formatPublished(article);
    el.textContent = text;
    el.style.display = text ? "" : "none";
    if (article.published) el.setAttribute("datetime", article.published);
    else el.removeAttribute("datetime");
    // Hovering shows the date exactly as the site printed it.
    el.title = article.date && article.date !== text ? "Source: " + article.date : "";
  }

  function buildPlaceholder() {
    var ph = document.createElement("div");
    ph.className = "media-placeholder";
    ph.setAttribute("aria-hidden", "true");
    ph.style.display = "flex";
    ph.style.alignItems = "center";
    ph.style.justifyContent = "center";
    ph.style.width = "100%";
    ph.style.height = "100%";
    ph.style.color = "#5a6187";
    ph.style.fontSize = "2rem";
    ph.textContent = "📰";
    return ph;
  }

  // ---- Rendering -----------------------------------------------------------

  function createPill(article) {
    var pill = document.createElement("button");
    pill.type = "button";
    pill.className = "pill";

    var media = document.createElement("div");
    media.className = "pill__media";
    media.appendChild(buildImage(article.image, article.title, "pill__image"));

    var body = document.createElement("div");
    body.className = "pill__body";

    var tags = buildTags(article);
    if (tags.childNodes.length) body.appendChild(tags);

    var title = document.createElement("h2");
    title.className = "pill__title";
    title.textContent = article.title || "Untitled";
    body.appendChild(title);

    var desc = document.createElement("p");
    desc.className = "pill__description";
    desc.textContent = truncate(article.description);
    body.appendChild(desc);

    if (article.published || article.date) {
      var date = document.createElement("time");
      date.className = "pill__date";
      fillDate(date, article);
      body.appendChild(date);
    }

    pill.appendChild(media);
    pill.appendChild(body);

    pill.addEventListener("click", function () {
      openModal(article);
    });

    return pill;
  }

  function render(articles) {
    feedEl.innerHTML = "";
    if (!articles.length) {
      statusEl.textContent = "No articles available.";
      statusEl.className = "status";
      return;
    }
    var frag = document.createDocumentFragment();
    articles.forEach(function (article) {
      frag.appendChild(createPill(article));
    });
    feedEl.appendChild(frag);
    statusEl.textContent = "";
    statusEl.className = "status";
    statusEl.style.display = "none";
  }

  // ---- Modal ---------------------------------------------------------------

  function openModal(article) {
    var mediaWrap = document.getElementById("modal-media");
    mediaWrap.innerHTML = "";
    mediaWrap.appendChild(buildImage(article.image, article.title, "modal__image"));

    var tagsEl = document.getElementById("modal-tags");
    tagsEl.innerHTML = "";
    var tags = buildTags(article);
    while (tags.firstChild) tagsEl.appendChild(tags.firstChild);
    tagsEl.style.display = tagsEl.childNodes.length ? "" : "none";

    document.getElementById("modal-title").textContent = article.title || "Untitled";

    fillDate(document.getElementById("modal-date"), article);

    document.getElementById("modal-description").textContent = article.description || "";

    var linkEl = document.getElementById("modal-link");
    if (isUrl(article.link)) {
      linkEl.href = article.link.trim();
      linkEl.classList.remove("is-disabled");
      linkEl.textContent = "Read full article";
    } else {
      linkEl.href = "#";
      linkEl.classList.add("is-disabled");
      linkEl.textContent = "Link unavailable";
    }

    modalEl.classList.add("is-open");
    modalEl.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
  }

  function closeModal() {
    modalEl.classList.remove("is-open");
    modalEl.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  }

  modalEl.addEventListener("click", function (e) {
    if (e.target.hasAttribute("data-close")) closeModal();
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && modalEl.classList.contains("is-open")) closeModal();
  });

  // ---- Load ----------------------------------------------------------------

  function load() {
    fetch(ENDPOINT)
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        render((data && data.articles) || []);
      })
      .catch(function (err) {
        statusEl.textContent =
          "Could not load articles from " + ENDPOINT + " (" + err.message + ").";
        statusEl.className = "status status--error";
      });
  }

  load();
})();

"""Turn the free-form dates sites print into ISO 8601 (UTC).

Sites write dates in every imaginable way: "2026-11-06T13:59:09Z",
"Thu, 06 Nov 2026 14:00:00 GMT", "Nov. 6, 2026", "2 hrs ago",
"Há 1 hora", "sexta-feira, 6 de novembro de 2026"... The raw text is kept in
the article's "date" field; this module adds a normalised "published" value
so articles from every source can be sorted and filtered together.

Fast paths handle ISO 8601 and RFC 2822 (RSS) dates; everything else goes to
the `dateparser` library when it is installed.
"""

import datetime as dt
import email.utils
import logging
import re

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None

try:
    import dateparser
except ImportError:  # pragma: no cover - optional dependency
    dateparser = None

log = logging.getLogger("news_provider")

_ISO_START = re.compile(r"^\d{4}-\d{2}-\d{2}")


def zone(name):
    """Return a tzinfo for an IANA name ("UTC", "America/Sao_Paulo")."""
    if not name or name.upper() == "UTC":
        return dt.timezone.utc
    if ZoneInfo is None:
        raise ValueError("time zones need Python 3.9+")
    try:
        return ZoneInfo(name)
    except Exception as exc:
        raise ValueError(f"unknown time zone {name!r}") from exc


def _from_iso(raw):
    if not _ISO_START.match(raw):
        return None
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _from_rfc2822(raw):
    if "," not in raw and not raw[:3].isalpha():
        return None
    try:
        return email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None


def _from_natural(raw, languages, timezone, now):
    if dateparser is None:
        return None
    settings = {
        "TIMEZONE": timezone or "UTC",
        "RETURN_AS_TIMEZONE_AWARE": True,
        "TO_TIMEZONE": "UTC",
        "PREFER_DATES_FROM": "past",
        "RELATIVE_BASE": now.astimezone(zone(timezone)).replace(tzinfo=None),
    }
    try:
        return dateparser.parse(raw, languages=languages or None, settings=settings)
    except Exception as exc:  # dateparser raises a zoo of exception types
        log.debug("dateparser failed on %r: %s", raw, exc)
        return None


def to_iso(raw, languages=None, timezone="UTC", now=None):
    """Return `raw` as an ISO 8601 UTC string ("2026-11-06T13:59:09Z") or ""."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    now = now or dt.datetime.now(dt.timezone.utc)

    parsed = _from_iso(raw) or _from_rfc2822(raw) or _from_natural(raw, languages, timezone, now)
    if parsed is None:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone(timezone))
    parsed = parsed.astimezone(dt.timezone.utc)

    # A date far in the future is a mis-parse (e.g. "11/05" read the wrong way).
    if parsed > now + dt.timedelta(days=1):
        return ""
    return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")

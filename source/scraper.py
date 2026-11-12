#!/usr/bin/env python3
"""Scraper for the municipalities of the province of Soria (es.wikipedia.org).

The script performs a two-level crawl:

    level 1 -> the annex page, used only as an index of links
    level 2 -> each municipality article, where the data actually lives

Design notes
------------
* Only public article pages are requested (`/wiki/...`); robots.txt is parsed
  and honoured before the first request.
* Requests are serialised with a configurable delay so the server is never
  hammered, and transient failures are retried with exponential backoff.
* Nothing is cleaned or imputed here: Práctica 2 is about cleaning. Missing
  values are exported as empty cells on purpose.

Usage
-----
    python scraper.py --limit 5            # smoke test on 5 municipalities
    python scraper.py --delay 1.5          # full run, slower and politer
"""

from __future__ import annotations

import argparse
import csv
import logging
import random
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from extract import discover_municipality_links, parse_infobox

DEFAULT_INDEX_URL = (
    "https://es.wikipedia.org/wiki/Anexo:Municipios_de_la_provincia_de_Soria"
)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; UOC-Practica1/1.0; "
    "+https://github.com/merayeret-eng/Municipios-Soria-Web-Scraping) Python-requests"
)

# Column order of the resulting CSV.
FIELDS = [
    "municipio",
    "comarca",
    "partido_judicial",
    "poblacion",
    "año_poblacion",
    "superficie_km2",
    "altitud_m",
    "densidad_hab_km2",
    "gentilicio",
    "codigo_postal",
    "alcalde",
    "partido_politico",
    "latitud",
    "longitud",
    "sitio_web",
    "titulo_articulo",
    "url",
    "fecha_extraccion",
]

log = logging.getLogger("scraper")


class PoliteSession:
    """A requests session that behaves like a well-mannered client."""

    def __init__(self, user_agent: str, delay: float, timeout: int, retries: int):
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Language": "es-ES,es;q=0.9",
                "Accept": "text/html,application/xhtml+xml",
            }
        )

    def check_robots(self, url: str) -> bool:
        """Return True when robots.txt allows fetching `url` with our agent.

        RobotFileParser.read() is not used here: it downloads robots.txt with
        urllib's default User-Agent, which Wikipedia answers with a 403. We
        download the file with our own session instead, so the rules are
        evaluated against the very agent we are going to send.

        Failure is not a single case. RFC 9309 (2.3.1) distinguishes them:
        a 4xx means the file does not exist, so there is no restriction; a 5xx
        or an unreachable server means "assume complete disallow". Treating
        both as "go ahead" would be a silent licence to crawl a server that is
        explicitly telling us it cannot answer.
        """
        parts = urlparse(url)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            response = self.session.get(robots_url, timeout=self.timeout)
        except requests.RequestException as exc:  # unreachable, not a verdict
            log.warning("Could not reach %s (%s); assuming disallow", robots_url, exc)
            return False
        if 400 <= response.status_code < 500:
            log.warning("%s returned HTTP %s; no restrictions declared",
                        robots_url, response.status_code)
            return True
        if response.status_code >= 500:
            log.warning("%s returned HTTP %s; assuming disallow",
                        robots_url, response.status_code)
            return False
        parser.parse(response.text.splitlines())
        allowed = parser.can_fetch(self.session.headers["User-Agent"], url)
        log.info("robots.txt -> can_fetch(%s) = %s", url, allowed)
        return allowed

    def get(self, url: str) -> str:
        """Fetch a URL politely: fixed delay + jitter, retries with backoff."""
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            time.sleep(self.delay + random.uniform(0, 0.4))
            try:
                response = self.session.get(url, timeout=self.timeout)
                if response.status_code == 200:
                    response.encoding = response.encoding or "utf-8"
                    return response.text
                if response.status_code == 429 or response.status_code >= 500:
                    wait = int(response.headers.get("Retry-After", 2 ** attempt))
                    log.warning(
                        "HTTP %s on %s, retrying in %ss (attempt %s/%s)",
                        response.status_code, url, wait, attempt, self.retries,
                    )
                    time.sleep(wait)
                    continue
                response.raise_for_status()
            except requests.RequestException as exc:
                last_error = exc
                wait = 2 ** attempt
                log.warning(
                    "%s on %s, retrying in %ss (attempt %s/%s)",
                    type(exc).__name__, url, wait, attempt, self.retries,
                )
                time.sleep(wait)
        raise RuntimeError(f"Could not download {url}: {last_error}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract a dataset of the municipalities of Soria from Wikipedia.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--index-url", default=DEFAULT_INDEX_URL,
                        help="Page used as the link index")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent.parent
                                             / "dataset" / "municipios_soria.csv"),
                        help="Output CSV path")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="Minimum seconds between two requests")
    parser.add_argument("--timeout", type=int, default=30, help="Per-request timeout")
    parser.add_argument("--retries", type=int, default=3, help="Attempts per URL")
    parser.add_argument("--limit", type=int, default=0,
                        help="Stop after N municipalities (0 = all); useful for tests")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT,
                        help="User-Agent sent with every request")
    return parser


def save_csv(rows: list[dict], out_path: Path) -> None:
    """Write the dataset as UTF-8 CSV (with BOM so Excel reads accents)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    log.info("Wrote %s rows to %s", len(rows), out_path)


def report_completeness(rows: list[dict]) -> None:
    """Print how many records have each field filled (raw evidence for §5)."""
    if not rows:
        return
    log.info("Completeness report (%s records):", len(rows))
    for field in FIELDS:
        filled = sum(1 for row in rows if row.get(field) not in (None, ""))
        log.info("  %-18s %3d/%3d (%5.1f%%)",
                 field, filled, len(rows), 100 * filled / len(rows))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    client = PoliteSession(args.user_agent, args.delay, args.timeout, args.retries)
    log.info("User-Agent in use: %s", client.session.headers["User-Agent"])

    if not client.check_robots(args.index_url):
        log.error("robots.txt forbids fetching %s; aborting.", args.index_url)
        return 2

    # Level 1: the index page gives us the navigation frontier.
    log.info("Reading index: %s", args.index_url)
    links = discover_municipality_links(client.get(args.index_url), args.index_url)
    log.info("Discovered %s municipality links", len(links))
    if args.limit:
        links = links[: args.limit]
        log.info("Limit active: processing only %s municipalities", len(links))

    # Level 2: visit every article and extract its record.
    rows: list[dict] = []
    failures: list[str] = []
    today = date.today().isoformat()
    try:
        for position, (name, url) in enumerate(links, start=1):
            log.info("[%s/%s] %s", position, len(links), name)
            try:
                record = parse_infobox(client.get(url), url)
            except Exception as exc:
                log.error("  failed: %s", exc)
                failures.append(f"{name} -> {url} ({exc})")
                continue
            row = {"municipio": name, "fecha_extraccion": today}
            row.update(record)
            rows.append(row)
    finally:
        # Partial results are still valuable if the run is interrupted.
        save_csv(rows, Path(args.out))

    report_completeness(rows)
    log.info("Done: %s ok, %s failed", len(rows), len(failures))
    for failure in failures:
        log.warning("  %s", failure)
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())

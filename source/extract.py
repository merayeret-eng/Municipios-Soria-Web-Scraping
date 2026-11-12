"""HTML extraction helpers for the Soria municipalities dataset.

This module contains no network code on purpose: it only turns HTML text into
Python data. Keeping extraction separate from downloading makes the parser
testable without hitting the server (see the `--limit` flag in scraper.py).
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin, unquote

from bs4 import BeautifulSoup

# Namespaces that are NOT municipality articles and must be ignored while
# discovering links (images, categories, annexes, special pages...).
SKIPPED_NAMESPACES = (
    "Archivo:",
    "Categoría:",
    "Categoria:",
    "Anexo:",
    "Especial:",
    "Special:",
    "Wikipedia:",
    "Plantilla:",
    "Ayuda:",
    "Portal:",
    "Discusión:",
)

# Small caps used as thousand separators in Spanish text (plain space, NBSP,
# narrow NBSP and thin space are all used by MediaWiki).
_SPACES = "\u0020\u00a0\u202f\u2009"

_NUMBER_RE = re.compile(r"[-+]?\d[\d.," + _SPACES + r"]*")
_YEAR_RE = re.compile(r"\(?\b(1[89]\d{2}|20\d{2})\b\)?")
_LATLON_RE = re.compile(r"(-?\d{1,3}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)")


def clean_text(node) -> str:
    """Return the visible text of a node with references and noise removed."""
    if node is None:
        return ""
    # Reference markers ("[1]", "[2]") live in <sup class="reference">.
    for ref in node.select("sup.reference, sup.noprint, style, script"):
        ref.decompose()
    text = node.get_text(" ", strip=True)
    text = text.replace("\u200b", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", text).strip()


def normalize_label(label: str) -> str:
    """Normalize an infobox label: drop bullets, spaces and accents."""
    label = label.replace("\u2022", " ").replace("\u00b7", " ")
    label = re.sub(r"\[.*?\]", "", label)
    label = re.sub(r"\s+", " ", label).strip()
    return label


def parse_number(raw: str) -> Optional[float]:
    """Convert a Spanish-formatted number ("1 397,5") into a float.

    Returns None when the text holds no number at all, so that missing data
    stays explicitly missing instead of becoming a fake zero.
    """
    if not raw:
        return None
    match = _NUMBER_RE.search(raw)
    if not match:
        return None
    token = match.group(0)
    for space in _SPACES:
        token = token.replace(space, "")
    token = token.rstrip(".,")
    if "," in token:                 # Spanish decimal comma
        token = token.replace(".", "").replace(",", ".")
    try:
        return float(token)
    except ValueError:
        return None


def parse_year(raw: str) -> Optional[int]:
    """Extract the reference year of a population figure (e.g. '287 hab. (2025)')."""
    if not raw:
        return None
    years = _YEAR_RE.findall(raw)
    return int(years[-1]) if years else None


def _is_article_href(href: str) -> bool:
    """True for links that point to an article in the main namespace."""
    if not href or not href.startswith(("/wiki/", "https://es.wikipedia.org/wiki/")):
        return False
    if "/wiki/Archivo:" in href or "/wiki/File:" in href:
        return False
    title = unquote(href.split("/wiki/", 1)[1])
    return not title.startswith(SKIPPED_NAMESPACES) and ":" not in title


def discover_municipality_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """Level 1 of the crawl: read the index table and return (name, url) pairs.

    The annex page lists one municipality per row, and the first cell of every
    row links to that municipality's own article. That link is what turns a
    single static table into a navigation graph.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.wikitable")
    if table is None:
        raise ValueError("Index page does not contain the expected 'wikitable'")

    seen: set[str] = set()
    found: list[tuple[str, str]] = []
    for row in table.select("tr")[1:]:          # row 0 is the header
        cells = row.select("th, td")
        if not cells:
            continue
        link = cells[0].select_one("a[href]")
        if link is None or not _is_article_href(link["href"]):
            continue
        name = clean_text(link)
        url = urljoin(base_url, link["href"])
        if url in seen:
            continue
        seen.add(url)
        found.append((name, url))
    return found


def parse_infobox(html: str, page_url: str) -> dict[str, Optional[str]]:
    """Level 2 of the crawl: turn one municipality article into a flat record.

    Every municipality article renders its data through the same template
    ({{Ficha de entidad subnacional}}), so the infobox is a stable extraction
    target. Fields that are absent are returned as None: no invention, no
    imputation (cleaning is the goal of Práctica 2, not of this script).
    """
    soup = BeautifulSoup(html, "html.parser")

    heading = soup.select_one("h1#firstHeading")
    record: dict[str, Optional[str]] = {
        "titulo_articulo": clean_text(heading),
        "url": page_url,
        "comarca": None,
        "partido_judicial": None,
        "poblacion": None,
        "anio_poblacion": None,
        "superficie_km2": None,
        "altitud_m": None,
        "densidad_hab_km2": None,
        "gentilicio": None,
        "codigo_postal": None,
        "alcalde": None,
        "partido_politico": None,
        "latitud": None,
        "longitud": None,
        "sitio_web": None,
    }

    infobox = soup.select_one("table.infobox")
    if infobox is None:
        return record

    for row in infobox.select("tr"):
        header = row.find("th")
        value_cell = row.find("td")
        if header is None or value_cell is None:
            continue
        label = normalize_label(clean_text(header))
        value = clean_text(value_cell)
        if not value:
            continue

        # 'Ubicación' carries the decimal coordinates at the end of the cell.
        if label.startswith("Ubicaci"):
            coords = _LATLON_RE.search(value)
            if coords:
                record["latitud"] = coords.group(1)
                record["longitud"] = coords.group(2)
        elif label.startswith("Comarca"):
            record["comarca"] = value
        elif label.startswith("Partido judicial"):
            record["partido_judicial"] = value
        elif label.startswith("Poblaci"):
            number = parse_number(value)
            record["poblacion"] = f"{number:.0f}" if number is not None else None
            year = parse_year(value)
            record["anio_poblacion"] = str(year) if year else None
        elif label.startswith("Superficie"):
            number = parse_number(value)
            record["superficie_km2"] = f"{number:.2f}" if number is not None else None
        elif label.startswith("Altitud"):
            number = parse_number(value)
            record["altitud_m"] = f"{number:.0f}" if number is not None else None
        elif label.startswith("Densidad"):
            number = parse_number(value)
            record["densidad_hab_km2"] = f"{number:.2f}" if number is not None else None
        elif label.startswith("Gentilicio"):
            record["gentilicio"] = value
        elif label.startswith("Código postal") or label.startswith("Codigo postal"):
            record["codigo_postal"] = value
        elif label.startswith("Alcalde"):
            match = re.search(r"\((.*?)\)\s*$", value)
            if match:
                record["partido_politico"] = match.group(1).strip()
                record["alcalde"] = value[: match.start()].strip()
            else:
                record["alcalde"] = value
        elif label.startswith("Sitio web"):
            record["sitio_web"] = value

    return record

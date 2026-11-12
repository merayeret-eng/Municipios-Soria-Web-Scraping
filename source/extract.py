"""Funciones de extracción de HTML para el dataset de municipios de Soria.

Este módulo no contiene código de red a propósito: solo convierte texto HTML
en datos de Python. Separar la extracción de la descarga hace que el parser se
pueda probar sin tocar el servidor (véase la opción `--limit` de scraper.py).
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin, unquote

from bs4 import BeautifulSoup

# Espacios de nombres que NO son artículos de municipio y hay que ignorar al
# descubrir enlaces (imágenes, categorías, anexos, páginas especiales...).
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

# Espacios usados como separador de millares en el texto español (espacio
# normal, NBSP, NBSP estrecho y espacio fino los usa MediaWiki).
_SPACES = "\u0020\u00a0\u202f\u2009"

_NUMBER_RE = re.compile(r"[-+]?\d[\d.," + _SPACES + r"]*")
_YEAR_RE = re.compile(r"\(?\b(1[89]\d{2}|20\d{2})\b\)?")
_LATLON_RE = re.compile(r"(-?\d{1,3}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)")


def clean_text(node) -> str:
    """Devuelve el texto visible de un nodo, sin referencias ni ruido."""
    if node is None:
        return ""
    # Los marcadores de referencia ("[1]", "[2]") van en <sup class="reference">.
    for ref in node.select("sup.reference, sup.noprint, style, script"):
        ref.decompose()
    text = node.get_text(" ", strip=True)
    text = text.replace("\u200b", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", text).strip()


def normalize_label(label: str) -> str:
    """Normaliza la etiqueta de una fila: quita viñetas, espacios y acentos."""
    label = label.replace("\u2022", " ").replace("\u00b7", " ")
    label = re.sub(r"\[.*?\]", "", label)
    label = re.sub(r"\s+", " ", label).strip()
    return label


def parse_number(raw: str) -> Optional[float]:
    """Convierte un número con formato español ("1 397,5") en un float.

    Devuelve None cuando el texto no contiene ningún número, de modo que un
    dato ausente siga siendo ausente y no se convierta en un cero falso.
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
    if "," in token:                 # coma decimal española
        token = token.replace(".", "").replace(",", ".")
    try:
        return float(token)
    except ValueError:
        return None


def parse_year(raw: str) -> Optional[int]:
    """Extrae el año de referencia de una cifra de población ('287 hab. (2025)')."""
    if not raw:
        return None
    years = _YEAR_RE.findall(raw)
    return int(years[-1]) if years else None


def _is_article_href(href: str) -> bool:
    """Devuelve True para enlaces que apuntan a un artículo del espacio principal."""
    if not href or not href.startswith(("/wiki/", "https://es.wikipedia.org/wiki/")):
        return False
    if "/wiki/Archivo:" in href or "/wiki/File:" in href:
        return False
    title = unquote(href.split("/wiki/", 1)[1])
    return not title.startswith(SKIPPED_NAMESPACES) and ":" not in title


def discover_municipality_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """Nivel 1 del recorrido: lee la tabla del índice y devuelve pares (nombre, url).

    La página del anexo lista un municipio por fila y la primera celda de cada
    fila enlaza al artículo propio de ese municipio. Ese enlace es lo que
    convierte una tabla estática en un grafo de navegación.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.wikitable")
    if table is None:
        raise ValueError("La página índice no contiene la tabla 'wikitable' esperada")

    seen: set[str] = set()
    found: list[tuple[str, str]] = []
    for row in table.select("tr")[1:]:          # la fila 0 es la cabecera
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
    """Nivel 2 del recorrido: convierte un artículo de municipio en un registro plano.

    Todos los artículos de municipio pintan sus datos con la misma plantilla
    ({{Ficha de entidad subnacional}}), así que la ficha es un objetivo de
    extracción estable. Los campos ausentes se devuelven como None: ni
    invención ni imputación (la limpieza es el objetivo de la Práctica 2, no de
    este script).
    """
    soup = BeautifulSoup(html, "html.parser")

    heading = soup.select_one("h1#firstHeading")
    record: dict[str, Optional[str]] = {
        "titulo_articulo": clean_text(heading),
        "url": page_url,
        "comarca": None,
        "partido_judicial": None,
        "poblacion": None,
        "año_poblacion": None,
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

        # La fila 'Ubicación' lleva las coordenadas decimales al final de la celda.
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
            record["año_poblacion"] = str(year) if year else None
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

#!/usr/bin/env python3
"""Scraper de los municipios de la provincia de Soria (es.wikipedia.org).

El script hace un recorrido en dos niveles:

    nivel 1 -> la página del anexo, usada solo como índice de enlaces
    nivel 2 -> el artículo de cada municipio, donde están los datos

Notas de diseño
---------------
* Solo se piden páginas públicas de artículo (`/wiki/...`); `robots.txt` se
  interpreta y se respeta antes de la primera petición.
* Las peticiones van en serie con un retardo configurable, para no castigar al
  servidor, y los fallos transitorios se reintentan con espera exponencial.
* Aquí no se limpia ni se imputa nada. Los
  valores ausentes se exportan como celda vacía a propósito.

Uso
---
    python scraper.py --limit 5            # prueba rápida con 5 municipios
    python scraper.py --delay 1.5          # recorrido completo, más lento
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

# Orden de las columnas del CSV resultante.
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
    """Sesión de `requests` que se comporta como un cliente bien educado."""

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
        """Devuelve True si robots.txt permite descargar `url` con nuestro agente.

        Aquí no se usa `RobotFileParser.read()`: ese método descarga robots.txt
        con el User-Agent por defecto de urllib, y Wikipedia le responde 403.
        Se descarga el archivo con la propia sesión, de modo que las reglas se
        evalúan contra el mismo agente que vamos a enviar.

        Un fallo al leer el archivo no significa siempre lo mismo. El RFC 9309
        (2.3.1) los distingue: un 4xx significa que el archivo no existe, así
        que no hay restricción; un 5xx o un servidor inalcanzable significan
        asumir prohibición. Tratar ambos casos como «adelante» sería un permiso
        silencioso para rastrear un servidor que nos está diciendo que no puede
        responder.
        """
        parts = urlparse(url)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            response = self.session.get(robots_url, timeout=self.timeout)
        except requests.RequestException as exc:  # inalcanzable, no es un veredicto
            log.warning("No se pudo acceder a %s (%s); se asume prohibido", robots_url, exc)
            return False
        if 400 <= response.status_code < 500:
            log.warning("%s devolvió HTTP %s; no declara restricciones",
                        robots_url, response.status_code)
            return True
        if response.status_code >= 500:
            log.warning("%s devolvió HTTP %s; se asume prohibido",
                        robots_url, response.status_code)
            return False
        parser.parse(response.text.splitlines())
        allowed = parser.can_fetch(self.session.headers["User-Agent"], url)
        log.info("robots.txt -> can_fetch(%s) = %s", url, allowed)
        return allowed

    def get(self, url: str) -> str:
        """Descarga una URL con retardo fijo más jitter y reintentos con espera."""
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
                        "HTTP %s en %s; reintento en %ss (intento %s/%s)",
                        response.status_code, url, wait, attempt, self.retries,
                    )
                    time.sleep(wait)
                    continue
                response.raise_for_status()
            except requests.RequestException as exc:
                last_error = exc
                wait = 2 ** attempt
                log.warning(
                    "%s en %s; reintento en %ss (intento %s/%s)",
                    type(exc).__name__, url, wait, attempt, self.retries,
                )
                time.sleep(wait)
        raise RuntimeError(f"No se pudo descargar {url}: {last_error}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extrae un dataset de los municipios de Soria desde la Wikipedia.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--index-url", default=DEFAULT_INDEX_URL,
                        help="Página que se usa como índice de enlaces")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent.parent
                                             / "dataset" / "municipios_soria.csv"),
                        help="Ruta del CSV de salida")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="Segundos mínimos entre dos peticiones")
    parser.add_argument("--timeout", type=int, default=30, help="Timeout por petición")
    parser.add_argument("--retries", type=int, default=3, help="Intentos por URL")
    parser.add_argument("--limit", type=int, default=0,
                        help="Se detiene tras N municipios (0 = todos); útil para pruebas")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT,
                        help="User-Agent que se envía en cada petición")
    return parser


def save_csv(rows: list[dict], out_path: Path) -> None:
    """Escribe el dataset en CSV UTF-8 (con BOM para que Excel lea los acentos)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    log.info("Escritas %s filas en %s", len(rows), out_path)


def report_completeness(rows: list[dict]) -> None:
    """Registra cuántos registros tienen cada campo relleno ."""
    if not rows:
        return
    log.info("Informe de completitud (%s registros):", len(rows))
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
    log.info("User-Agent en uso: %s", client.session.headers["User-Agent"])

    if not client.check_robots(args.index_url):
        log.error("robots.txt prohíbe descargar %s; se aborta.", args.index_url)
        return 2

    # Nivel 1: la página índice nos da la frontera de navegación.
    log.info("Leyendo el índice: %s", args.index_url)
    links = discover_municipality_links(client.get(args.index_url), args.index_url)
    log.info("Encontrados %s enlaces de municipios", len(links))
    if args.limit:
        links = links[: args.limit]
        log.info("Límite activo: se procesan solo %s municipios", len(links))

    # Nivel 2: se visita cada artículo y se extrae su registro.
    rows: list[dict] = []
    failures: list[str] = []
    today = date.today().isoformat()
    try:
        for position, (name, url) in enumerate(links, start=1):
            log.info("[%s/%s] %s", position, len(links), name)
            try:
                record = parse_infobox(client.get(url), url)
            except Exception as exc:
                log.error("  error: %s", exc)
                failures.append(f"{name} -> {url} ({exc})")
                continue
            row = {"municipio": name, "fecha_extraccion": today}
            row.update(record)
            rows.append(row)
    finally:
        # Un resultado parcial sigue siendo útil si el recorrido se interrumpe.
        save_csv(rows, Path(args.out))

    report_completeness(rows)
    log.info("Terminado: %s correctos, %s fallidos", len(rows), len(failures))
    for failure in failures:
        log.warning("  %s", failure)
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())

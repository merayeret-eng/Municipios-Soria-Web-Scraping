# Municipios de la provincia de Soria — scraping de la Wikipedia

Dataset con los **183 municipios** de la provincia de Soria (comarca, partido judicial, población,
superficie, altitud, densidad, gentilicio, código postal, alcaldía, coordenadas y sitio web),
extraído de la Wikipedia en español con un scraper propio en Python.

**Autor:** Aaron Mera — Máster Data Science UOC, M2.851 Tipología y ciclo de vida de los datos
**Sitio de origen:** https://es.wikipedia.org/wiki/Anexo:Municipios_de_la_provincia_de_Soria
**DOI:** https://doi.org/10.5281/zenodo.24164219
**Licencia:** datos CC BY-SA 4.0 · código MIT

---

## Dataset

| Archivo | Filas | Columnas | Fuente |
|---|---|---|---|
| `dataset/municipios_soria.csv` | 183 | 18 | Wikipedia en español (anexo de municipios de Soria) |

Una fila por municipio. Población con referencia **2025**; extracción del **11/11/2026**.
UTF-8 con BOM, separador coma. Sin limpiar: conserva las ausencias e inconsistencias de la fuente.

### Variables

- **7 numéricas:** `poblacion`, `año_poblacion`, `superficie_km2`, `altitud_m`,
  `densidad_hab_km2`, `latitud`, `longitud`
- **10 de texto:** `municipio`, `comarca`, `partido_judicial`, `gentilicio`, `codigo_postal`,
  `alcalde`, `partido_politico`, `sitio_web`, `titulo_articulo`, `url`
- **1 fecha:** `fecha_extraccion`

Cobertura por campo: `gentilicio` 54,1 %, `sitio_web` 86,3 %, `superficie_km2` 98,4 %,
`partido_judicial` 98,9 %; el resto, 100 %.

---

## Tecnología

- **Python 3.13** con `requests` + `BeautifulSoup`
- **Navegación en dos niveles:** el anexo provincial actúa como índice y enlaza los 183 artículos
- **Sin API:** toda la extracción es HTML

---

## Estructura

```
.
├── README.md                  Este archivo
├── LICENSE                    MIT para el código; CC BY-SA 4.0 para el dataset
├── requirements.txt           Librerías y versiones
├── source/
│   ├── scraper.py             Red, ritmo de peticiones, robots.txt y escritura del CSV
│   └── extract.py             Parseo del HTML: descubrimiento de enlaces y ficha del municipio
└── dataset/
    └── municipios_soria.csv   Dataset resultante (183 × 18)
```

| Archivo | Qué hace |
|---|---|
| `source/scraper.py` | Comprueba `robots.txt`, descarga el índice, recorre los enlaces descubiertos, aplica el retardo entre peticiones y escribe el CSV. Contiene la interfaz de línea de comandos. |
| `source/extract.py` | Convierte HTML en datos. `discover_municipality_links()` obtiene los enlaces del índice; `parse_infobox()` convierte la ficha de cada municipio en un registro. Sin red, se puede probar aislado. |
| `dataset/municipios_soria.csv` | Salida de la ejecución completa: 183 municipios, 18 columnas. |

---

## Cómo usar el código

### 1. Requisitos

Python 3.9 o superior (la ejecución de referencia usó 3.13) y las dependencias de `requirements.txt`.

### 2. Instalación

```bash
python -m venv .venv

# Linux / macOS
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

### 3. Ejecución

El script se lanza desde `source/`, porque importa `extract.py`:

```bash
cd source
python scraper.py
```

Por defecto recorre los 183 municipios y escribe `../dataset/municipios_soria.csv`. Tarda unos
5 minutos: hay al menos 1 segundo entre peticiones.

### 4. Parámetros

| Parámetro | Por defecto | Descripción |
|---|---|---|
| `--index-url` | `https://es.wikipedia.org/wiki/Anexo:Municipios_de_la_provincia_de_Soria` | Página usada como índice de enlaces |
| `--out` | `../dataset/municipios_soria.csv` | Ruta del CSV de salida |
| `--delay` | `1.0` | Segundos mínimos entre peticiones (más un jitter de hasta 0,4 s) |
| `--timeout` | `30` | Timeout por petición, en segundos |
| `--retries` | `3` | Intentos por URL, con espera exponencial |
| `--limit` | `0` | Procesa solo N municipios (0 = todos) |
| `--user-agent` | `Mozilla/5.0 (compatible; UOC-Practica1/1.0; ...)` | User-Agent de cada petición |

### 5. Salida

CSV con cabecera y una fila por municipio. El progreso y el informe de completitud por campo se
escriben en la salida de error. Si `robots.txt` no permite la página índice, el programa termina
con código 2 **sin hacer ninguna petición de datos**.

---

## Atribución

Los datos proceden de la Wikipedia en español (Fundación Wikimedia), publicada bajo
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Este dataset es una obra derivada
y se distribuye bajo la misma licencia. Cada fila incluye la `url` de origen.

## Licencia

- **Código:** MIT (ver `LICENSE`).
- **Dataset:** CC BY-SA 4.0.

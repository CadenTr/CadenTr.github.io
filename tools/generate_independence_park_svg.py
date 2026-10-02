"""Build a static Independence Park context diagram from Mecklenburg County GIS.

The output is a general-reference visual for the portfolio. It uses the county's
published park boundary and street centerline feature services. It is not a
survey or a boundary opinion.
"""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "images" / "independence-park-boundary.svg"

PARK_LAYER = (
    "https://meckgis.mecklenburgcountync.gov/server/rest/services/"
    "ParkBoundaries/FeatureServer/0/query"
)
STREET_LAYER = (
    "https://meckgis.mecklenburgcountync.gov/server/rest/services/"
    "StreetCenterline/FeatureServer/0/query"
)

# A small context window around the official park geometry.
BBOX = (-80.8290, 35.2105, -80.8190, 35.2195)
STREETS = {
    "Armory Dr",
    "Charlottetowne Av",
    "E 7th St",
    "E Independence Bv",
    "Hawthorne Ln",
    "Park Dr",
}


def query(url: str, **params: str) -> dict:
    encoded = urllib.parse.urlencode({"f": "json", **params})
    request = urllib.request.Request(
        f"{url}?{encoded}",
        headers={"Accept": "application/json", "User-Agent": "CadenTrahanPortfolio/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def fetch_geometry() -> tuple[list[list[list[float]]], list[dict]]:
    park = query(
        PARK_LAYER,
        where="objectid=227",
        outFields="objectid,property,sum_acres",
        returnGeometry="true",
        outSR="4326",
        geometryPrecision="7",
    )
    if not park.get("features"):
        raise RuntimeError("Independence Park boundary was not returned by the county service")

    xmin, ymin, xmax, ymax = BBOX
    streets = query(
        STREET_LAYER,
        where="1=1",
        geometry=f"{xmin},{ymin},{xmax},{ymax}",
        geometryType="esriGeometryEnvelope",
        inSR="4326",
        spatialRel="esriSpatialRelIntersects",
        outFields="objectid,wholestname,streetclass",
        returnGeometry="true",
        outSR="4326",
        geometryPrecision="7",
    )

    selected = [
        feature
        for feature in streets.get("features", [])
        if feature.get("attributes", {}).get("wholestname") in STREETS
    ]
    return park["features"][0]["geometry"]["rings"], selected


def svg_path(points: list[list[float]], project) -> str:
    coords = [project(lon, lat) for lon, lat in points]
    return "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in coords)


def build_svg(rings: list[list[list[float]]], streets: list[dict]) -> str:
    width, height = 1000, 700
    left, top, map_width, map_height = 64, 104, 872, 470
    xmin, ymin, xmax, ymax = BBOX
    latitude = (ymin + ymax) / 2
    x_scale = math.cos(math.radians(latitude))
    data_width = (xmax - xmin) * x_scale
    data_height = ymax - ymin
    scale = min(map_width / data_width, map_height / data_height)
    used_width = data_width * scale
    used_height = data_height * scale
    x_offset = left + (map_width - used_width) / 2
    y_offset = top + (map_height - used_height) / 2

    def project(lon: float, lat: float) -> tuple[float, float]:
        x = x_offset + ((lon - xmin) * x_scale) * scale
        y = y_offset + (ymax - lat) * scale
        return x, y

    road_paths: list[str] = []
    road_paths_emphasis: list[str] = []
    for feature in streets:
        name = feature["attributes"]["wholestname"]
        for path in feature.get("geometry", {}).get("paths", []):
            d = svg_path(path, project)
            road_paths.append(f'<path class="road road-casing" d="{d}"/>')
            klass = "road road-major" if name in {"Hawthorne Ln", "E 7th St"} else "road"
            road_paths_emphasis.append(f'<path class="{klass}" d="{d}"/>')

    park_paths = []
    for index, ring in enumerate(rings, start=1):
        d = svg_path(ring, project) + " Z"
        park_paths.append(f'<path class="park-shape park-shape-{index}" d="{d}"/>')

    # Label anchors were checked against the same official street-centerline service.
    anchors = {
        "UPPER PARK": (-80.82472, 35.21662),
        "LOWER PARK": (-80.82116, 35.21385),
        "HAWTHORNE LN": (-80.82243, 35.21545),
        "E 7TH ST": (-80.82565, 35.21810),
        "PARK DR": (-80.82020, 35.21488),
        "ARMORY DR": (-80.82745, 35.21528),
    }
    labels = []
    rotations = {
        "HAWTHORNE LN": -39,
        "E 7TH ST": -39,
        "PARK DR": 62,
        "ARMORY DR": -40,
    }
    for label, (lon, lat) in anchors.items():
        x, y = project(lon, lat)
        if label in {"UPPER PARK", "LOWER PARK"}:
            labels.append(f'<text class="park-label" x="{x:.1f}" y="{y:.1f}">{label}</text>')
        else:
            rotate = rotations.get(label, 0)
            labels.append(
                f'<text class="road-label" x="{x:.1f}" y="{y:.1f}" '
                f'transform="rotate({rotate} {x:.1f} {y:.1f})">{label}</text>'
            )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
  <title id="title">Current Independence Park boundary and street context</title>
  <desc id="desc">Two-part current park footprint split by Hawthorne Lane, with East Seventh Street, Park Drive, Armory Drive, and nearby street context. Derived from Mecklenburg County GIS.</desc>
  <defs>
    <pattern id="grid" width="34" height="34" patternUnits="userSpaceOnUse">
      <path d="M34 0H0V34" fill="none" stroke="#f4a340" stroke-opacity=".07" stroke-width="1"/>
    </pattern>
    <filter id="shadow" x="-25%" y="-25%" width="150%" height="150%">
      <feDropShadow dx="0" dy="9" stdDeviation="10" flood-color="#000" flood-opacity=".26"/>
    </filter>
  </defs>
  <style>
    .road {{ fill:none; stroke:#b7c0bf; stroke-width:2.4; stroke-linecap:round; stroke-linejoin:round; opacity:.56 }}
    .road-casing {{ stroke:#071115; stroke-width:9; opacity:.78 }}
    .road-major {{ stroke:#f2eee4; stroke-width:4.2; opacity:.88 }}
    .park-shape {{ fill:#f4a340; fill-opacity:.22; stroke:#f4a340; stroke-width:3.8; stroke-linejoin:round; filter:url(#shadow) }}
    .park-shape-2 {{ fill-opacity:.15 }}
    text {{ font-family: ui-monospace, SFMono-Regular, Consolas, monospace; letter-spacing:.11em }}
    .park-label {{ fill:#fffaf0; font-size:18px; font-weight:700; text-anchor:middle; paint-order:stroke; stroke:#0b171b; stroke-width:5 }}
    .road-label {{ fill:#d8ddda; font-size:11px; font-weight:700; text-anchor:middle; paint-order:stroke; stroke:#0b171b; stroke-width:4 }}
  </style>
  <rect width="1000" height="700" rx="22" fill="#0b171b"/>
  <rect width="1000" height="700" rx="22" fill="url(#grid)"/>
  <text x="48" y="49" fill="#f4a340" font-size="13" font-weight="700">INDEPENDENCE PARK / CURRENT GIS FOOTPRINT</text>
  <text x="48" y="76" fill="#b7c0bf" font-size="12">21.08 GIS ACRES · TWO PARK SECTIONS · GENERAL REFERENCE</text>
  <g>{''.join(road_paths)}{''.join(road_paths_emphasis)}{''.join(park_paths)}{''.join(labels)}</g>
  <g transform="translate(904 34)">
    <path d="M16 42V0M16 0 8 13M16 0l8 13" fill="none" stroke="#f2eee4" stroke-width="2"/>
    <text x="16" y="58" fill="#f2eee4" font-size="11" text-anchor="middle">N</text>
  </g>
  <g transform="translate(48 615)">
    <rect width="18" height="18" rx="2" fill="#f4a340" fill-opacity=".24" stroke="#f4a340" stroke-width="2"/>
    <text x="30" y="14" fill="#d8ddda" font-size="11">CURRENT PARK BOUNDARY</text>
    <path d="M254 9h36" stroke="#f2eee4" stroke-width="4" stroke-linecap="round"/>
    <text x="302" y="14" fill="#d8ddda" font-size="11">STREET CENTERLINE</text>
  </g>
  <line x1="48" y1="650" x2="952" y2="650" stroke="#f2eee4" stroke-opacity=".18"/>
  <text x="48" y="677" fill="#8f9a99" font-size="9">SOURCE: MECKLENBURG COUNTY GIS PARK BOUNDARIES + STREET CENTERLINE · RETRIEVED 2026-10-02 · NOT A SURVEY</text>
</svg>
'''


def main() -> None:
    rings, streets = fetch_geometry()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(build_svg(rings, streets), encoding="utf-8")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()

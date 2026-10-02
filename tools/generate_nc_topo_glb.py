"""Build the interactive North Carolina layered-topography model and profile.

The source geometry is the same QGIS work used for the laser-cut map. The
registered base, 25 ft, and 50 ft sheets come from the corrected low-layer
package; higher sheets come from the master GeoPackage. Every physical sheet is
a separate closed glTF node so the website can reveal the stack one layer at a
time.

Run with the QGIS Python environment on Windows::

    "C:\\Program Files\\QGIS 4.2.2\\bin\\python-qgis.bat" tools\\generate_nc_topo_glb.py
"""

from __future__ import annotations

import csv
import json
import math
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence
from xml.sax.saxutils import escape as xml_escape

import numpy as np
from osgeo import ogr
from shapely import constrained_delaunay_triangles, from_wkb, get_parts, make_valid, union_all
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.prepared import prep


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = Path(
    r"C:\Users\caden\Documents\Codex\2026-09-28\i-m-building-a-laser-cut\outputs\NC_Topo_Master"
)
MASTER_GPKG = SOURCE_ROOT / "geo" / "nc_topo.gpkg"
REGISTERED_GPKG = (
    SOURCE_ROOT
    / "CPCC_25_50_registered_fixed_seam_package"
    / "NC_low_three_registered_fixed_seam.gpkg"
)
AUDIT_GPKG = SOURCE_ROOT / "QGIS_registration_smoothing_audit.gpkg"
PIN_SCHEDULE = (
    SOURCE_ROOT
    / "3D_Print_Registration_Pins"
    / "Permanent_Elevator_Posts"
    / "permanent_elevator_post_schedule.csv"
)

OUTPUT_GLB = REPO_ROOT / "assets" / "models" / "nc-topo-layered.glb"
OUTPUT_MANIFEST = REPO_ROOT / "assets" / "models" / "nc-topo-layered.json"
OUTPUT_PROFILE = REPO_ROOT / "assets" / "images" / "nc-topo-profile.svg"

# A 300 m simplification retains the recognizable vector coastline and
# contours while keeping 54 closed solids practical in a portfolio browser.
SIMPLIFY_TOLERANCE_M = 300.0
REGION_BLEND_M = 12_000.0
MODEL_WIDTH = 10.0
MODEL_STACK_HEIGHT = 1.65
HOLE_DIAMETER_MM = 2.3

REGION_ORDER = ("coastalPlain", "piedmont", "mountains")
REGION_SOURCE_LAYERS = {
    "coastalPlain": "region_coastal_plain",
    "piedmont": "region_piedmont",
    "mountains": "region_mountains",
}
REGION_LABELS = {
    "coastalPlain": "Coastal Plain",
    "piedmont": "Piedmont",
    "mountains": "Mountains",
}
REGION_MAX_ELEVATION = {
    "coastalPlain": 650,
    "piedmont": 2200,
    "mountains": 5600,
}
# Short tonal ramps preserve each region's primary hue: blue coast, yellow
# Piedmont, red mountains.
REGION_PALETTES = {
    "coastalPlain": ((44, 122, 176), (93, 180, 215)),
    "piedmont": ((188, 148, 43), (238, 202, 83)),
    "mountains": ((166, 64, 56), (226, 103, 82)),
}


@dataclass(frozen=True)
class Pin:
    pin_id: str
    panel: str
    x: float
    y: float
    stop_after_ft: int
    cover_ft: int
    sheet_count_below_cover: int
    shaft_height_mm: float
    hole: BaseGeometry


class LayerMesh:
    """Indexed, colored triangle mesh for one physical sheet."""

    def __init__(self) -> None:
        self.positions: list[tuple[float, float, float]] = []
        self.colors: list[tuple[int, int, int, int]] = []
        self.indices: list[int] = []
        self._vertex_index: dict[tuple[float, float, float, int, int, int, int], int] = {}

    def vertex(
        self,
        position: tuple[float, float, float],
        color: tuple[int, int, int, int],
    ) -> int:
        key = (
            round(position[0], 6),
            round(position[1], 6),
            round(position[2], 6),
            color[0],
            color[1],
            color[2],
            color[3],
        )
        existing = self._vertex_index.get(key)
        if existing is not None:
            return existing
        index = len(self.positions)
        self.positions.append(position)
        self.colors.append(color)
        self._vertex_index[key] = index
        return index

    def triangle(
        self,
        points: Sequence[tuple[float, float, float]],
        colors: Sequence[tuple[int, int, int, int]],
        desired_y_normal: int = 0,
    ) -> None:
        ids = [self.vertex(points[i], colors[i]) for i in range(3)]
        if desired_y_normal:
            a, b, c = points
            ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
            ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
            normal_y = ab[2] * ac[0] - ab[0] * ac[2]
            if normal_y * desired_y_normal < 0:
                ids[1], ids[2] = ids[2], ids[1]
        self.indices.extend(ids)


def layer_geometry(gpkg: Path, layer_name: str) -> BaseGeometry:
    dataset = ogr.Open(str(gpkg), 0)
    if dataset is None:
        raise RuntimeError(f"Could not open {gpkg}")
    layer = dataset.GetLayerByName(layer_name)
    if layer is None:
        available = [dataset.GetLayerByIndex(i).GetName() for i in range(dataset.GetLayerCount())]
        raise RuntimeError(f"Missing {layer_name!r} in {gpkg}; available: {available}")
    geometries: list[BaseGeometry] = []
    for feature in layer:
        geometry = feature.GetGeometryRef()
        if geometry is not None and not geometry.IsEmpty():
            geometries.append(from_wkb(bytes(geometry.ExportToWkb())))
    dataset = None
    return polygonal(union_all(geometries)) if geometries else Polygon()


def layer_records(gpkg: Path, layer_name: str) -> list[tuple[dict[str, object], BaseGeometry]]:
    dataset = ogr.Open(str(gpkg), 0)
    if dataset is None:
        raise RuntimeError(f"Could not open {gpkg}")
    layer = dataset.GetLayerByName(layer_name)
    if layer is None:
        raise RuntimeError(f"Missing {layer_name!r} in {gpkg}")
    definition = layer.GetLayerDefn()
    field_names = [definition.GetFieldDefn(i).GetName() for i in range(definition.GetFieldCount())]
    records: list[tuple[dict[str, object], BaseGeometry]] = []
    for feature in layer:
        geometry = feature.GetGeometryRef()
        if geometry is None or geometry.IsEmpty():
            continue
        fields = {name: feature.GetField(name) for name in field_names}
        records.append((fields, from_wkb(bytes(geometry.ExportToWkb()))))
    dataset = None
    return records


def polygon_parts(geometry: BaseGeometry) -> Iterator[Polygon]:
    if geometry.is_empty:
        return
    if isinstance(geometry, Polygon):
        yield geometry
        return
    if isinstance(geometry, MultiPolygon):
        yield from geometry.geoms
        return
    for part in get_parts(geometry):
        if isinstance(part, Polygon):
            yield part
        elif isinstance(part, MultiPolygon):
            yield from part.geoms


def polygonal(geometry: BaseGeometry) -> BaseGeometry:
    """Repair geometry and retain only polygonal parts."""
    if geometry.is_empty:
        return Polygon()
    repaired = make_valid(geometry)
    polygons = list(polygon_parts(repaired))
    if not polygons:
        return Polygon()
    return polygons[0] if len(polygons) == 1 else union_all(polygons)


def simplify_polygonal(geometry: BaseGeometry) -> BaseGeometry:
    return polygonal(geometry.simplify(SIMPLIFY_TOLERANCE_M, preserve_topology=True))


def lerp_color(
    left: Sequence[int], right: Sequence[int], amount: float, alpha: int = 255
) -> tuple[int, int, int, int]:
    amount = max(0.0, min(1.0, amount))
    return (
        int(round(left[0] + (right[0] - left[0]) * amount)),
        int(round(left[1] + (right[1] - left[1]) * amount)),
        int(round(left[2] + (right[2] - left[2]) * amount)),
        alpha,
    )


def shade(color: Sequence[int], factor: float) -> tuple[int, int, int, int]:
    return (
        max(0, min(255, int(round(color[0] * factor)))),
        max(0, min(255, int(round(color[1] * factor)))),
        max(0, min(255, int(round(color[2] * factor)))),
        int(color[3]) if len(color) > 3 else 255,
    )


def region_color(region: str, elevation: int) -> tuple[int, int, int, int]:
    low, high = REGION_PALETTES[region]
    t = 0.12 + 0.78 * min(max(elevation, 0) / REGION_MAX_ELEVATION[region], 1.0)
    return lerp_color(low, high, t)


def elevation_levels() -> list[int]:
    dataset = ogr.Open(str(MASTER_GPKG), 0)
    if dataset is None:
        raise RuntimeError(f"Could not open {MASTER_GPKG}")
    values: list[int] = []
    for i in range(dataset.GetLayerCount()):
        name = dataset.GetLayerByIndex(i).GetName()
        if name.startswith("nf_fab_") and name.endswith("ft"):
            elevation = int(name.removeprefix("nf_fab_").removesuffix("ft"))
            # The master also retains four empty, above-summit template layers
            # (5,800-6,600 ft). The physical build ends at the last nonempty
            # 5,600 ft sheet.
            if elevation <= 5600:
                values.append(elevation)
    dataset = None
    return sorted(values)


def load_pins() -> list[Pin]:
    holes = {
        str(fields["pin_id"]): polygonal(geometry)
        for fields, geometry in layer_records(AUDIT_GPKG, "registration_holes")
    }
    centers = {
        str(fields["pin_id"]): geometry
        for fields, geometry in layer_records(AUDIT_GPKG, "registration_centers")
    }
    schedule: dict[str, dict[str, str]] = {}
    with PIN_SCHEDULE.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            schedule[row["pin_id"]] = row

    pins: list[Pin] = []
    for pin_id in ("W3", "W1", "W2", "E2", "E1", "E3"):
        if pin_id not in holes or pin_id not in centers or pin_id not in schedule:
            raise RuntimeError(f"Incomplete registration data for {pin_id}")
        row = schedule[pin_id]
        center = centers[pin_id]
        x = float(center.x)
        y = float(center.y)
        if (
            abs(x - float(row["qgis_epsg32119_x_m"])) > 0.01
            or abs(y - float(row["qgis_epsg32119_y_m"])) > 0.01
        ):
            raise RuntimeError(f"Registration center mismatch for {pin_id}")
        pins.append(
            Pin(
                pin_id=pin_id,
                panel=str(row["panel"]),
                x=x,
                y=y,
                stop_after_ft=int(row["last_holed_layer_ft"]),
                cover_ft=int(row["intact_cover_layer_ft"]),
                sheet_count_below_cover=int(row["sheet_count_below_cover"]),
                shaft_height_mm=float(row["shaft_height_mm"]),
                hole=holes[pin_id],
            )
        )
    return pins


def build_unperforated_outlines(levels: Sequence[int], pins: Sequence[Pin]) -> list[BaseGeometry]:
    all_holes = union_all([pin.hole for pin in pins])
    base = simplify_polygonal(layer_geometry(REGISTERED_GPKG, "registered_base").union(all_holes))
    outlines = [base]
    for elevation in levels:
        if elevation == 25:
            source = layer_geometry(REGISTERED_GPKG, "registered_25").union(all_holes)
        elif elevation == 50:
            source = layer_geometry(REGISTERED_GPKG, "registered_50").union(all_holes)
        else:
            source = layer_geometry(MASTER_GPKG, f"nf_fab_{elevation:04d}ft")
        source = simplify_polygonal(polygonal(source))
        # Enforce nesting before subtracting pin holes, so the first intact
        # cover can correctly close a lower registration hole.
        nested = polygonal(source.intersection(outlines[-1]))
        if nested.is_empty:
            raise RuntimeError(f"Layer {elevation} ft became empty during nesting")
        outlines.append(nested)
    return outlines


def build_region_partition(base: BaseGeometry) -> dict[str, BaseGeometry]:
    candidates = {
        name: simplify_polygonal(layer_geometry(MASTER_GPKG, layer).intersection(base))
        for name, layer in REGION_SOURCE_LAYERS.items()
    }
    assigned: dict[str, BaseGeometry] = {}
    used: BaseGeometry = Polygon()
    for name in REGION_ORDER:
        assigned[name] = polygonal(candidates[name].difference(used).intersection(base))
        used = polygonal(used.union(assigned[name]))

    # Source physiographic polygons leave small unclassified slivers. Assign
    # each component to the nearest named region so every top face is colored.
    for component in polygon_parts(polygonal(base.difference(used))):
        sample = component.representative_point()
        nearest = min(
            REGION_ORDER,
            key=lambda name: (sample.distance(candidates[name]), REGION_ORDER.index(name)),
        )
        assigned[nearest] = polygonal(assigned[nearest].union(component))

    used = Polygon()
    for name in REGION_ORDER:
        assigned[name] = polygonal(assigned[name].difference(used).intersection(base))
        used = polygonal(used.union(assigned[name]))
    for component in polygon_parts(polygonal(base.difference(used))):
        sample = component.representative_point()
        nearest = min(REGION_ORDER, key=lambda name: sample.distance(assigned[name]))
        assigned[nearest] = polygonal(assigned[nearest].union(component))

    covered = polygonal(union_all(list(assigned.values())))
    missing_ratio = base.difference(covered).area / base.area
    overlap_area = sum(
        assigned[a].intersection(assigned[b]).area
        for i, a in enumerate(REGION_ORDER)
        for b in REGION_ORDER[i + 1 :]
    )
    if missing_ratio > 1e-8 or overlap_area > base.area * 1e-8:
        raise RuntimeError(
            f"Region partition failed: missing={missing_ratio:.3e}, overlap={overlap_area:.3f}"
        )
    return assigned


def build_shared_boundaries(regions: dict[str, BaseGeometry]) -> dict[tuple[str, str], BaseGeometry]:
    return {
        pair: regions[pair[0]].boundary.intersection(regions[pair[1]].boundary)
        for pair in (("coastalPlain", "piedmont"), ("piedmont", "mountains"))
    }


def active_holes(outline: BaseGeometry, elevation: int, pins: Sequence[Pin]) -> list[Pin]:
    return [
        pin
        for pin in pins
        if elevation <= pin.stop_after_ft and outline.covers(Point(pin.x, pin.y))
    ]


def triangulate(geometry: BaseGeometry) -> Iterator[Polygon]:
    if geometry.is_empty:
        return
    for triangle in polygon_parts(constrained_delaunay_triangles(geometry)):
        if triangle.area > 1e-6:
            yield triangle


def model_transform(
    x: float,
    y: float,
    vertical: float,
    bounds: tuple[float, float, float, float],
) -> tuple[float, float, float]:
    min_x, min_y, max_x, max_y = bounds
    model_depth = MODEL_WIDTH * (max_y - min_y) / (max_x - min_x)
    return (
        (x - min_x) / (max_x - min_x) * MODEL_WIDTH - MODEL_WIDTH / 2.0,
        vertical,
        (y - min_y) / (max_y - min_y) * model_depth - model_depth / 2.0,
    )


def sheet_mesh(
    solid: BaseGeometry,
    elevation: int,
    layer_index: int,
    layer_count: int,
    regions: dict[str, BaseGeometry],
    shared_boundaries: dict[tuple[str, str], BaseGeometry],
    bounds: tuple[float, float, float, float],
) -> LayerMesh:
    mesh = LayerMesh()
    slab_height = MODEL_STACK_HEIGHT / layer_count
    bottom_y = layer_index * slab_height
    top_y = (layer_index + 1) * slab_height

    adjacency: dict[str, list[tuple[str, BaseGeometry]]] = {name: [] for name in REGION_ORDER}
    for (left, right), boundary in shared_boundaries.items():
        adjacency[left].append((right, boundary))
        adjacency[right].append((left, boundary))
    boundary_buffers = {
        name: union_all(
            [line.buffer(REGION_BLEND_M, cap_style=2, join_style=2) for _, line in adjacent]
        )
        if adjacent
        else Polygon()
        for name, adjacent in adjacency.items()
    }

    def top_vertex_color(region: str, x: float, y: float, is_band: bool) -> tuple[int, int, int, int]:
        base = region_color(region, elevation)
        if not is_band:
            return base
        point = Point(x, y)
        neighbor, boundary = min(adjacency[region], key=lambda item: point.distance(item[1]))
        distance = point.distance(boundary)
        blend = 0.5 * max(0.0, 1.0 - distance / REGION_BLEND_M)
        return lerp_color(base, region_color(neighbor, elevation), blend)

    top_zones: list[BaseGeometry] = []
    for region in REGION_ORDER:
        region_sheet = polygonal(solid.intersection(regions[region]))
        if region_sheet.is_empty:
            continue
        band_buffer = boundary_buffers[region]
        zones = (
            ((polygonal(region_sheet.difference(band_buffer)), False),
             (polygonal(region_sheet.intersection(band_buffer)), True))
            if not band_buffer.is_empty
            else ((region_sheet, False),)
        )
        for zone, is_band in zones:
            if zone.is_empty:
                continue
            top_zones.append(zone)
            for triangle in triangulate(zone):
                coordinates = list(triangle.exterior.coords)[:3]
                points = [model_transform(x, y, top_y, bounds) for x, y in coordinates]
                colors = [top_vertex_color(region, x, y, is_band) for x, y in coordinates]
                mesh.triangle(points, colors, desired_y_normal=1)

    top_coverage = polygonal(union_all(top_zones))
    coverage_error = solid.symmetric_difference(top_coverage).area / max(solid.area, 1.0)
    if coverage_error > 1e-7:
        raise RuntimeError(f"Region top coverage error on layer {elevation}: {coverage_error:.3e}")

    bottom_color = (26, 31, 34, 255)
    for triangle in triangulate(solid):
        coordinates = list(triangle.exterior.coords)[:3]
        points = [model_transform(x, y, bottom_y, bounds) for x, y in coordinates]
        mesh.triangle(points, [bottom_color] * 3, desired_y_normal=-1)

    prepared_regions = {name: prep(geometry) for name, geometry in regions.items()}
    side_color_cache: dict[tuple[float, float], tuple[int, int, int, int]] = {}

    def side_color(x: float, y: float) -> tuple[int, int, int, int]:
        key = (round(x, 3), round(y, 3))
        if key in side_color_cache:
            return side_color_cache[key]
        point = Point(x, y)
        region = next(
            (name for name in REGION_ORDER if prepared_regions[name].covers(point)),
            min(REGION_ORDER, key=lambda name: point.distance(regions[name])),
        )
        color = region_color(region, elevation)
        if adjacency[region]:
            neighbor, boundary = min(adjacency[region], key=lambda item: point.distance(item[1]))
            distance = point.distance(boundary)
            if distance < REGION_BLEND_M:
                color = lerp_color(
                    color,
                    region_color(neighbor, elevation),
                    0.5 * (1.0 - distance / REGION_BLEND_M),
                )
        result = shade(color, 0.67)
        side_color_cache[key] = result
        return result

    for polygon in polygon_parts(solid):
        for ring in [polygon.exterior, *polygon.interiors]:
            coordinates = list(ring.coords)
            for (ax, ay), (bx, by) in zip(coordinates, coordinates[1:]):
                if math.isclose(ax, bx, abs_tol=1e-8) and math.isclose(ay, by, abs_tol=1e-8):
                    continue
                a_bottom = model_transform(ax, ay, bottom_y, bounds)
                b_bottom = model_transform(bx, by, bottom_y, bounds)
                b_top = model_transform(bx, by, top_y, bounds)
                a_top = model_transform(ax, ay, top_y, bounds)
                color_a = side_color(ax, ay)
                color_b = side_color(bx, by)
                mesh.triangle((a_bottom, b_bottom, b_top), (color_a, color_b, color_b))
                mesh.triangle((a_bottom, b_top, a_top), (color_a, color_b, color_a))
    return mesh


def align4(data: bytearray, pad: bytes = b"\x00") -> None:
    while len(data) % 4:
        data.extend(pad)


def write_glb(
    layer_meshes: Sequence[LayerMesh], layer_metadata: Sequence[dict[str, object]]
) -> None:
    binary = bytearray()
    buffer_views: list[dict[str, object]] = []
    accessors: list[dict[str, object]] = []

    def add_buffer_view(payload: bytes, target: int) -> int:
        align4(binary)
        offset = len(binary)
        binary.extend(payload)
        index = len(buffer_views)
        buffer_views.append(
            {"buffer": 0, "byteOffset": offset, "byteLength": len(payload), "target": target}
        )
        return index

    def add_accessor(
        view: int,
        component_type: int,
        count: int,
        accessor_type: str,
        *,
        normalized: bool = False,
        minimum: list[float] | None = None,
        maximum: list[float] | None = None,
    ) -> int:
        accessor: dict[str, object] = {
            "bufferView": view,
            "componentType": component_type,
            "count": count,
            "type": accessor_type,
        }
        if normalized:
            accessor["normalized"] = True
        if minimum is not None:
            accessor["min"] = minimum
        if maximum is not None:
            accessor["max"] = maximum
        index = len(accessors)
        accessors.append(accessor)
        return index

    meshes: list[dict[str, object]] = []
    nodes: list[dict[str, object]] = []
    for mesh_data, metadata in zip(layer_meshes, layer_metadata, strict=True):
        positions = np.asarray(mesh_data.positions, dtype="<f4")
        colors = np.asarray(mesh_data.colors, dtype=np.uint8)
        indices = np.asarray(mesh_data.indices, dtype="<u4")
        position_accessor = add_accessor(
            add_buffer_view(positions.tobytes(), 34962),
            5126,
            len(positions),
            "VEC3",
            minimum=[float(value) for value in positions.min(axis=0)],
            maximum=[float(value) for value in positions.max(axis=0)],
        )
        color_accessor = add_accessor(
            add_buffer_view(colors.tobytes(), 34962), 5121, len(colors), "VEC4", normalized=True
        )
        index_accessor = add_accessor(
            add_buffer_view(indices.tobytes(), 34963), 5125, len(indices), "SCALAR"
        )
        mesh_index = len(meshes)
        meshes.append(
            {
                "name": metadata["nodeName"],
                "primitives": [
                    {
                        "attributes": {"POSITION": position_accessor, "COLOR_0": color_accessor},
                        "indices": index_accessor,
                        "material": 0,
                        "mode": 4,
                    }
                ],
                "extras": {
                    "layerIndex": metadata["index"],
                    "elevation": metadata["elevation"],
                },
            }
        )
        nodes.append(
            {
                "name": metadata["nodeName"],
                "mesh": mesh_index,
                "extras": {
                    "layerIndex": metadata["index"],
                    "elevation": metadata["elevation"],
                    "label": metadata["label"],
                    "activeRegistrationHoles": metadata["activeHoleIds"],
                },
            }
        )

    align4(binary)
    document = {
        "asset": {"version": "2.0", "generator": "Caden Trahan NC topo vector layer generator"},
        "extensionsUsed": ["KHR_materials_unlit"],
        "extensionsRequired": ["KHR_materials_unlit"],
        "scene": 0,
        "scenes": [{"name": "NC layered topography", "nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": [
            {
                "name": "Region vertex colors",
                "doubleSided": True,
                "pbrMetallicRoughness": {
                    "baseColorFactor": [1.0, 1.0, 1.0, 1.0],
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.92,
                },
                "extensions": {"KHR_materials_unlit": {}},
            }
        ],
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(binary)}],
        "extras": {
            "layerCount": len(nodes),
            "coordinateSystem": "X east-west, Y physical sheet stack, Z north-south",
            "sourceCrs": "EPSG:32119",
        },
    }
    json_bytes = bytearray(json.dumps(document, separators=(",", ":")).encode("utf-8"))
    align4(json_bytes, b" ")
    total_length = 12 + 8 + len(json_bytes) + 8 + len(binary)
    glb = bytearray(struct.pack("<4sII", b"glTF", 2, total_length))
    glb.extend(struct.pack("<I4s", len(json_bytes), b"JSON"))
    glb.extend(json_bytes)
    glb.extend(struct.pack("<I4s", len(binary), b"BIN\x00"))
    glb.extend(binary)
    OUTPUT_GLB.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_GLB.write_bytes(glb)


def color_hex(color: Sequence[int]) -> str:
    return f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"


def write_profile_svg(
    levels: Sequence[int],
    outlines: Sequence[BaseGeometry],
    pins: Sequence[Pin],
    pin_regions: dict[str, str],
) -> dict[str, object]:
    width, height = 1600, 860
    plot_left, plot_right = 150.0, 1450.0
    top, bottom = 190.0, 710.0
    band_height = (bottom - top) / len(outlines)
    min_x, max_x = min(pin.x for pin in pins), max(pin.x for pin in pins)
    elevations = [0, *levels]

    def pin_x(pin: Pin) -> float:
        return plot_left + (pin.x - min_x) / (max_x - min_x) * (plot_right - plot_left)

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">North Carolina topographic sheet and registration-pin profile</title>',
        '<desc id="desc">A west-to-east section through registration pins W3, W1, W2, E2, E1, and E3. Each narrow band is one physical sheet. Gaps are drilled registration holes and outlined bands are intact cover sheets.</desc>',
        "<defs>",
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0a1116"/><stop offset="1" stop-color="#101b22"/></linearGradient>',
        '<filter id="glow"><feGaussianBlur stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
        "<style>",
        ".title{font:700 30px 'Segoe UI',sans-serif;fill:#f3f7f8}.sub{font:16px 'Segoe UI',sans-serif;fill:#9fb1b9}.pin{font:700 19px 'Segoe UI',sans-serif;fill:#eef5f6}.detail{font:13px 'Segoe UI',sans-serif;fill:#aabac0}.axis{font:12px 'Segoe UI',sans-serif;fill:#82979f}.legend{font:14px 'Segoe UI',sans-serif;fill:#c4d0d4}.fine{font:11px 'Segoe UI',sans-serif;fill:#779099}.guide{stroke:#29404b;stroke-width:1;stroke-dasharray:4 6}",
        "</style></defs>",
        f'<rect width="{width}" height="{height}" rx="24" fill="url(#bg)"/>',
        '<text class="title" x="72" y="60">Registration profile · W3 → W1 → W2 → E2 → E1 → E3</text>',
        '<text class="sub" x="72" y="91">54 equal-thickness sheets, derived from the registered QGIS layer geometry</text>',
        f'<line class="guide" x1="90" y1="{top:.2f}" x2="1515" y2="{top:.2f}"/>',
        f'<line class="guide" x1="90" y1="{bottom:.2f}" x2="1515" y2="{bottom:.2f}"/>',
        f'<text class="axis" x="82" y="{top + 4:.2f}" text-anchor="end">5,600 ft</text>',
        f'<text class="axis" x="82" y="{bottom + 4:.2f}" text-anchor="end">base</text>',
    ]

    column_width, gap_width = 92.0, 20.0
    for pin in pins:
        x = pin_x(pin)
        region = pin_regions[pin.pin_id]
        point = Point(pin.x, pin.y)
        presence = [outline.covers(point) for outline in outlines]
        hole_indices = {
            index
            for index, (elevation, present) in enumerate(zip(elevations, presence, strict=True))
            if present and elevation <= pin.stop_after_ft
        }
        cover_index = elevations.index(pin.cover_ft)
        shaft_top = bottom - pin.sheet_count_below_cover * band_height + 1.5
        svg.append(
            f'<rect x="{x - 3.5:.2f}" y="{shaft_top:.2f}" width="7" height="{bottom - shaft_top:.2f}" rx="2" fill="#b7c8cd" opacity=".86" filter="url(#glow)"/>'
        )
        svg.append(f'<line class="guide" x1="{x:.2f}" y1="124" x2="{x:.2f}" y2="{bottom + 18:.2f}"/>')
        for index, (elevation, present) in enumerate(zip(elevations, presence, strict=True)):
            if not present:
                continue
            y = bottom - (index + 1) * band_height
            fill = color_hex(region_color(region, elevation))
            if index in hole_indices:
                half = (column_width - gap_width) / 2.0
                svg.append(
                    f'<rect x="{x - column_width / 2:.2f}" y="{y + .45:.2f}" width="{half:.2f}" height="{max(band_height - .9, .6):.2f}" fill="{fill}"/>'
                )
                svg.append(
                    f'<rect x="{x + gap_width / 2:.2f}" y="{y + .45:.2f}" width="{half:.2f}" height="{max(band_height - .9, .6):.2f}" fill="{fill}"/>'
                )
            else:
                stroke = "#f4fafb" if index == cover_index else "none"
                stroke_width = "2.2" if index == cover_index else "0"
                svg.append(
                    f'<rect x="{x - column_width / 2:.2f}" y="{y + .45:.2f}" width="{column_width:.2f}" height="{max(band_height - .9, .6):.2f}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"/>'
                )
        svg.extend(
            [
                f'<text class="pin" x="{x:.2f}" y="140" text-anchor="middle">{xml_escape(pin.pin_id)}</text>',
                f'<text class="detail" x="{x:.2f}" y="160" text-anchor="middle">{xml_escape(REGION_LABELS[region])}</text>',
                f'<text class="detail" x="{x:.2f}" y="{bottom + 35:.2f}" text-anchor="middle">hole to {pin.stop_after_ft:,} ft</text>',
                f'<text class="detail" x="{x:.2f}" y="{bottom + 54:.2f}" text-anchor="middle">cover at {pin.cover_ft:,} ft</text>',
            ]
        )

    legend_y = 810
    svg.extend(
        [
            f'<rect x="72" y="{legend_y - 15}" width="48" height="10" fill="#3e94c5"/>',
            f'<rect x="92" y="{legend_y - 15}" width="9" height="10" fill="#0d171c"/>',
            f'<text class="legend" x="132" y="{legend_y - 6}">2.3 mm registration hole (width enlarged in section)</text>',
            f'<rect x="520" y="{legend_y - 16}" width="48" height="12" fill="#cf9f35" stroke="#f4fafb" stroke-width="2"/>',
            f'<text class="legend" x="580" y="{legend_y - 6}">first intact cover sheet</text>',
            f'<rect x="865" y="{legend_y - 17}" width="7" height="16" rx="2" fill="#b7c8cd"/>',
            f'<text class="legend" x="884" y="{legend_y - 6}">steel elevator post</text>',
            f'<text class="fine" x="1528" y="{legend_y - 6}" text-anchor="end">horizontal pin spacing follows EPSG:32119 coordinates</text>',
            "</svg>",
        ]
    )
    OUTPUT_PROFILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PROFILE.write_text("\n".join(svg) + "\n", encoding="utf-8")
    return {
        "path": "assets/images/nc-topo-profile.svg",
        "order": [pin.pin_id for pin in pins],
        "top": top,
        "bottom": bottom,
        "bandHeight": band_height,
        "layerCount": len(outlines),
        "viewBox": [0, 0, width, height],
    }


def write_section_profile_svg(
    levels: Sequence[int],
    outlines: Sequence[BaseGeometry],
    pins: Sequence[Pin],
    regions: dict[str, BaseGeometry],
    bounds: tuple[float, float, float, float],
) -> dict[str, object]:
    """Render the actual sheet intersections along the six-pin section line."""

    width, height = 1600, 920
    plot_left, plot_right = 95.0, 1510.0
    top, bottom = 305.0, 715.0
    band_height = (bottom - top) / len(outlines)
    elevations = [0, *levels]
    section = LineString([(pin.x, pin.y) for pin in pins])
    section_length = section.length
    prepared_regions = {name: prep(geometry) for name, geometry in regions.items()}

    def linear_parts(geometry: BaseGeometry) -> Iterator[LineString]:
        if geometry.is_empty:
            return
        if isinstance(geometry, LineString):
            if geometry.length > 1e-7:
                yield geometry
            return
        if isinstance(geometry, MultiLineString):
            yield from (line for line in geometry.geoms if line.length > 1e-7)
            return
        for item in get_parts(geometry):
            if isinstance(item, LineString) and item.length > 1e-7:
                yield item
            elif isinstance(item, MultiLineString):
                yield from (line for line in item.geoms if line.length > 1e-7)

    def station_x(station: float) -> float:
        return plot_left + station / section_length * (plot_right - plot_left)

    def region_at(point: Point) -> str:
        return next(
            (name for name in REGION_ORDER if prepared_regions[name].covers(point)),
            min(REGION_ORDER, key=lambda name: point.distance(regions[name])),
        )

    breaks = {0.0, section_length}
    for name in REGION_ORDER:
        for part in linear_parts(section.intersection(regions[name])):
            breaks.add(section.project(Point(part.coords[0])))
            breaks.add(section.project(Point(part.coords[-1])))
    stations = sorted(breaks)
    region_intervals: list[tuple[float, float, str]] = []
    for start, end in zip(stations, stations[1:]):
        if end - start < 1e-6:
            continue
        name = region_at(section.interpolate((start + end) / 2.0))
        if region_intervals and region_intervals[-1][2] == name:
            previous = region_intervals.pop()
            region_intervals.append((previous[0], end, name))
        else:
            region_intervals.append((start, end, name))
    if not region_intervals:
        raise RuntimeError("The registration section did not cross a terrain region")

    def gradient_stops(elevation: int) -> list[tuple[float, tuple[int, int, int, int]]]:
        stops: list[tuple[float, tuple[int, int, int, int]]] = [
            (0.0, region_color(region_intervals[0][2], elevation))
        ]
        for index in range(len(region_intervals) - 1):
            left, right = region_intervals[index], region_intervals[index + 1]
            transition = (left[1] + right[0]) / 2.0
            half_width = min(
                REGION_BLEND_M,
                max((left[1] - left[0]) * 0.24, 1.0),
                max((right[1] - right[0]) * 0.24, 1.0),
            )
            left_color = region_color(left[2], elevation)
            right_color = region_color(right[2], elevation)
            stops.extend(
                [
                    (max(left[0], transition - half_width), left_color),
                    (transition, lerp_color(left_color, right_color, 0.5)),
                    (min(right[1], transition + half_width), right_color),
                ]
            )
        stops.append((section_length, region_color(region_intervals[-1][2], elevation)))
        return sorted(stops, key=lambda item: item[0])

    def polygon_svg_path(geometry: BaseGeometry, x_map, y_map) -> str:
        commands: list[str] = []
        for polygon in polygon_parts(geometry):
            for ring in [polygon.exterior, *polygon.interiors]:
                coordinates = list(ring.coords)
                if not coordinates:
                    continue
                commands.append(f"M{x_map(coordinates[0][0]):.1f},{y_map(coordinates[0][1]):.1f}")
                commands.extend(f"L{x_map(x):.1f},{y_map(y):.1f}" for x, y in coordinates[1:])
                commands.append("Z")
        return "".join(commands)

    plan_x, plan_y, plan_width, plan_height = 1015.0, 88.0, 510.0, 176.0
    min_x, min_y, max_x, max_y = bounds
    source_aspect = (max_x - min_x) / (max_y - min_y)
    if source_aspect > plan_width / plan_height:
        draw_width = plan_width - 24.0
        draw_height = draw_width / source_aspect
    else:
        draw_height = plan_height - 24.0
        draw_width = draw_height * source_aspect
    draw_left = plan_x + (plan_width - draw_width) / 2.0
    draw_top = plan_y + (plan_height - draw_height) / 2.0

    def plan_map_x(value: float) -> float:
        return draw_left + (value - min_x) / (max_x - min_x) * draw_width

    def plan_map_y(value: float) -> float:
        return draw_top + draw_height - (value - min_y) / (max_y - min_y) * draw_height

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">North Carolina topographic sheet and registration-pin profile</title>',
        '<desc id="desc">A true unwrapped west-to-east section through W3, W1, W2, E2, E1, and E3. Every horizontal band is the actual intersection of one solid QGIS sheet with the bent section line.</desc>',
        "<defs>",
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0a1116"/><stop offset="1" stop-color="#101b22"/></linearGradient>',
        '<filter id="glow"><feGaussianBlur stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
        "<style>",
        ".title{font:700 29px 'Segoe UI',sans-serif;fill:#f3f7f8}.sub{font:15px 'Segoe UI',sans-serif;fill:#9fb1b9}.pin{font:700 15px 'Segoe UI',sans-serif;fill:#eef5f6}.detail{font:12px 'Segoe UI',sans-serif;fill:#aabac0}.axis{font:12px 'Segoe UI',sans-serif;fill:#82979f}.legend{font:14px 'Segoe UI',sans-serif;fill:#c4d0d4}.fine{font:11px 'Segoe UI',sans-serif;fill:#779099}.guide{stroke:#29404b;stroke-width:1;stroke-dasharray:4 6}.plan-label{font:700 10px 'Segoe UI',sans-serif;fill:#f7fafb;paint-order:stroke;stroke:#0b1419;stroke-width:3px}.cover{fill:none;stroke:#f4fafb;stroke-width:2}.band{shape-rendering:geometricPrecision}",
        "</style>",
    ]
    for index, elevation in enumerate(elevations):
        svg.append(
            f'<linearGradient id="layerGradient{index}" gradientUnits="userSpaceOnUse" x1="{plot_left:.2f}" x2="{plot_right:.2f}" y1="0" y2="0">'
        )
        for station, color in gradient_stops(elevation):
            svg.append(
                f'<stop offset="{station / section_length * 100.0:.5f}%" stop-color="{color_hex(color)}"/>'
            )
        svg.append("</linearGradient>")
    svg.extend(
        [
            "</defs>",
            f'<rect width="{width}" height="{height}" rx="24" fill="url(#bg)"/>',
            '<text class="title" x="72" y="60">Registration profile · W3 → W1 → W2 → E2 → E1 → E3</text>',
            '<text class="sub" x="72" y="91">Actual sheet intersections unwrapped by cumulative section distance</text>',
            f'<rect x="{plan_x:.1f}" y="{plan_y:.1f}" width="{plan_width:.1f}" height="{plan_height:.1f}" rx="12" fill="#0c171d" stroke="#2b424d"/>',
        ]
    )
    for name in REGION_ORDER:
        svg.append(
            f'<path d="{polygon_svg_path(regions[name], plan_map_x, plan_map_y)}" fill="{color_hex(region_color(name, 0))}" fill-opacity=".66" fill-rule="evenodd"/>'
        )
    svg.append(
        f'<path d="{polygon_svg_path(outlines[0], plan_map_x, plan_map_y)}" fill="none" stroke="#90a8b2" stroke-width="1.1" fill-rule="evenodd"/>'
    )
    section_points = " ".join(
        f"{plan_map_x(pin.x):.1f},{plan_map_y(pin.y):.1f}" for pin in pins
    )
    svg.append(
        f'<polyline points="{section_points}" fill="none" stroke="#f59e0b" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" filter="url(#glow)"/>'
    )
    for index, pin in enumerate(pins):
        px, py = plan_map_x(pin.x), plan_map_y(pin.y)
        label_offset = -8 if index % 2 == 0 else 14
        svg.extend(
            [
                f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.5" fill="#f7fafb" stroke="#f59e0b" stroke-width="1.5"/>',
                f'<text class="plan-label" x="{px:.1f}" y="{py + label_offset:.1f}" text-anchor="middle">{xml_escape(pin.pin_id)}</text>',
            ]
        )
    svg.extend(
        [
            f'<text class="fine" x="{plan_x + 14:.1f}" y="{plan_y + 18:.1f}">PLAN · actual section trace</text>',
            f'<line class="guide" x1="90" y1="{top:.2f}" x2="1515" y2="{top:.2f}"/>',
            f'<line class="guide" x1="90" y1="{bottom:.2f}" x2="1515" y2="{bottom:.2f}"/>',
            f'<text class="axis" x="82" y="{top + 4:.2f}" text-anchor="end">5,600 ft</text>',
            f'<text class="axis" x="82" y="{bottom + 4:.2f}" text-anchor="end">base</text>',
        ]
    )

    # Intersect each finished solid sheet, including scheduled holes, with the
    # complete bent section and unwrap every resulting span by station.
    for index, (elevation, outline) in enumerate(zip(elevations, outlines, strict=True)):
        holes = active_holes(outline, elevation, pins)
        solid = (
            polygonal(outline.difference(union_all([pin.hole for pin in holes])))
            if holes
            else outline
        )
        y = bottom - (index + 1) * band_height + 0.35
        for part in linear_parts(solid.intersection(section)):
            part_stations = [section.project(Point(coordinate)) for coordinate in part.coords]
            start, end = min(part_stations), max(part_stations)
            x1, x2 = station_x(start), station_x(end)
            if x2 - x1 >= 0.08:
                svg.append(
                    f'<rect class="band" x="{x1:.3f}" y="{y:.3f}" width="{x2 - x1:.3f}" height="{max(band_height - .7, .55):.3f}" fill="url(#layerGradient{index})"/>'
                )

    # Guides identify the exact pin stations; a white outline marks each first
    # intact cover sheet where the section closes over that registration hole.
    for pin in pins:
        station = section.project(Point(pin.x, pin.y))
        x = station_x(station)
        cover_index = elevations.index(pin.cover_ft)
        cover_y = bottom - (cover_index + 1) * band_height + 0.25
        svg.extend(
            [
                f'<line class="guide" x1="{x:.2f}" y1="{top - 8:.2f}" x2="{x:.2f}" y2="{bottom + 15:.2f}"/>',
                f'<rect class="cover" x="{x - 7:.2f}" y="{cover_y:.2f}" width="14" height="{max(band_height - .5, 1):.2f}" rx="1"/>',
                f'<text class="pin" x="{x:.2f}" y="{bottom + 34:.2f}" text-anchor="middle">{xml_escape(pin.pin_id)}</text>',
                f'<text class="detail" x="{x:.2f}" y="{bottom + 52:.2f}" text-anchor="middle">hole ≤ {pin.stop_after_ft:,}</text>',
                f'<text class="detail" x="{x:.2f}" y="{bottom + 68:.2f}" text-anchor="middle">cover {pin.cover_ft:,} ft</text>',
            ]
        )

    legend_y = 875
    svg.extend(
        [
            f'<rect x="72" y="{legend_y - 15}" width="48" height="10" fill="#3e94c5"/>',
            f'<rect x="93" y="{legend_y - 15}" width="6" height="10" fill="#0d171c"/>',
            f'<text class="legend" x="132" y="{legend_y - 6}">actual 2.3 mm registration-hole intersection</text>',
            f'<rect x="520" y="{legend_y - 16}" width="48" height="12" fill="#cf9f35" stroke="#f4fafb" stroke-width="2"/>',
            f'<text class="legend" x="580" y="{legend_y - 6}">first intact cover sheet</text>',
            f'<line x1="865" y1="{legend_y - 10}" x2="902" y2="{legend_y - 10}" stroke="#f59e0b" stroke-width="3"/>',
            f'<text class="legend" x="914" y="{legend_y - 6}">plan section trace</text>',
            f'<text class="fine" x="1528" y="{legend_y - 6}" text-anchor="end">horizontal scale is cumulative section distance</text>',
            "</svg>",
        ]
    )
    OUTPUT_PROFILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PROFILE.write_text("\n".join(svg) + "\n", encoding="utf-8")
    return {
        "path": "assets/images/nc-topo-profile.svg",
        "order": [pin.pin_id for pin in pins],
        "left": plot_left,
        "right": plot_right,
        "top": top,
        "bottom": bottom,
        "bandHeight": band_height,
        "layerCount": len(outlines),
        "viewBox": [0, 0, width, height],
        "sectionLengthMeters": section_length,
        "plan": {
            "x": plan_x,
            "y": plan_y,
            "width": plan_width,
            "height": plan_height,
        },
        "regionIntervals": [
            {"start": start, "end": end, "region": name}
            for start, end, name in region_intervals
        ],
    }


def inspect_glb(path: Path) -> dict[str, int]:
    payload = path.read_bytes()
    magic, version, total_length = struct.unpack_from("<4sII", payload, 0)
    if magic != b"glTF" or version != 2 or total_length != len(payload):
        raise RuntimeError("Generated GLB header is invalid")
    json_length, chunk_type = struct.unpack_from("<I4s", payload, 12)
    if chunk_type != b"JSON":
        raise RuntimeError("Generated GLB is missing its JSON chunk")
    document = json.loads(payload[20 : 20 + json_length].decode("utf-8"))
    nodes = document.get("nodes", [])
    meshes = document.get("meshes", [])
    if len(nodes) != 54 or len(meshes) != 54:
        raise RuntimeError(f"Expected 54 nodes and meshes; got {len(nodes)} and {len(meshes)}")
    for expected, node in enumerate(nodes):
        extras = node.get("extras", {})
        if extras.get("layerIndex") != expected or "elevation" not in extras:
            raise RuntimeError(f"Node {expected} is missing slider metadata")
    return {
        "bytes": len(payload),
        "nodes": len(nodes),
        "meshes": len(meshes),
        "accessors": len(document.get("accessors", [])),
        "bufferViews": len(document.get("bufferViews", [])),
    }


def main() -> int:
    required = (MASTER_GPKG, REGISTERED_GPKG, AUDIT_GPKG, PIN_SCHEDULE)
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        print("Missing source data:", *missing, sep="\n  ", file=sys.stderr)
        return 1

    levels = elevation_levels()
    if len(levels) != 53 or levels[0] != 25 or levels[-1] != 5600:
        raise RuntimeError(f"Expected 53 physical elevation layers from 25 to 5600 ft; got {levels}")
    elevations = [0, *levels]
    pins = load_pins()
    outlines = build_unperforated_outlines(levels, pins)
    if len(outlines) != 54:
        raise RuntimeError(f"Expected 54 sheet outlines; got {len(outlines)}")

    base = outlines[0]
    bounds = tuple(float(value) for value in base.bounds)
    min_x, min_y, max_x, max_y = bounds
    model_depth = MODEL_WIDTH * (max_y - min_y) / (max_x - min_x)
    regions = build_region_partition(base)
    shared_boundaries = build_shared_boundaries(regions)
    prepared_regions = {name: prep(geometry) for name, geometry in regions.items()}
    pin_regions: dict[str, str] = {}
    for pin in pins:
        point = Point(pin.x, pin.y)
        pin_regions[pin.pin_id] = next(
            (name for name in REGION_ORDER if prepared_regions[name].covers(point)),
            min(REGION_ORDER, key=lambda name: point.distance(regions[name])),
        )

    if "--profile-only" in sys.argv:
        if not OUTPUT_MANIFEST.exists() or not OUTPUT_GLB.exists():
            raise RuntimeError("Build the GLB and manifest before using --profile-only")
        profile_metadata = write_section_profile_svg(
            levels, outlines, pins, regions, bounds
        )
        manifest = json.loads(OUTPUT_MANIFEST.read_text(encoding="utf-8"))
        manifest["profile"] = profile_metadata
        OUTPUT_MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"Updated {OUTPUT_PROFILE}")
        print(f"Updated profile metadata in {OUTPUT_MANIFEST}")
        return 0

    layer_meshes: list[LayerMesh] = []
    layer_metadata: list[dict[str, object]] = []
    layer_count = len(outlines)
    for index, (elevation, outline) in enumerate(zip(elevations, outlines, strict=True)):
        holes = active_holes(outline, elevation, pins)
        solid = (
            polygonal(outline.difference(union_all([pin.hole for pin in holes])))
            if holes
            else outline
        )
        label = "Base" if elevation == 0 else f"{elevation:,} ft"
        node_name = "layer_00_base" if elevation == 0 else f"layer_{index:02d}_{elevation:04d}ft"
        mesh = sheet_mesh(
            solid, elevation, index, layer_count, regions, shared_boundaries, bounds
        )
        layer_meshes.append(mesh)
        metadata = {
            "index": index,
            "nodeName": node_name,
            "elevation": elevation,
            "label": label,
            "activeHoleIds": [pin.pin_id for pin in holes],
            "vertexCount": len(mesh.positions),
            "triangleCount": len(mesh.indices) // 3,
        }
        layer_metadata.append(metadata)
        print(
            f"[{index + 1:02d}/{layer_count}] {label:>8}  "
            f"vertices={len(mesh.positions):>7,}  triangles={len(mesh.indices) // 3:>7,}  "
            f"holes={','.join(metadata['activeHoleIds']) or 'none'}"
        )

    write_glb(layer_meshes, layer_metadata)
    profile_metadata = write_section_profile_svg(levels, outlines, pins, regions, bounds)

    pin_manifest: list[dict[str, object]] = []
    for pin in pins:
        point = Point(pin.x, pin.y)
        presence = [outline.covers(point) for outline in outlines]
        hole_indices = [
            index
            for index, (elevation, present) in enumerate(zip(elevations, presence, strict=True))
            if present and elevation <= pin.stop_after_ft
        ]
        model_position = model_transform(pin.x, pin.y, 0.0, bounds)
        pin_manifest.append(
            {
                "id": pin.pin_id,
                "panel": pin.panel,
                "region": pin_regions[pin.pin_id],
                "sourcePosition": {"x": pin.x, "y": pin.y},
                "normalizedPosition": {
                    "x": (pin.x - min_x) / (max_x - min_x),
                    "y": (pin.y - min_y) / (max_y - min_y),
                },
                "modelPosition": {"x": model_position[0], "z": model_position[2]},
                "lastHoledElevation": pin.stop_after_ft,
                "coverElevation": pin.cover_ft,
                "lastHoledLayerIndex": elevations.index(pin.stop_after_ft),
                "coverLayerIndex": elevations.index(pin.cover_ft),
                "sheetCountBelowCover": pin.sheet_count_below_cover,
                "shaftHeightMm": pin.shaft_height_mm,
                "holeDiameterMm": HOLE_DIAMETER_MM,
                "presentLayerIndices": [index for index, present in enumerate(presence) if present],
                "holeLayerIndices": hole_indices,
            }
        )

    inspection = inspect_glb(OUTPUT_GLB)
    manifest = {
        "version": 1,
        "model": "assets/models/nc-topo-layered.glb",
        "sourceCrs": "EPSG:32119",
        "coordinateSystem": {
            "x": "east-west",
            "y": "vertical physical sheet stack",
            "z": "north-south",
            "origin": "center of the simplified registered base extent",
        },
        "sourceExtent": {"minX": min_x, "minY": min_y, "maxX": max_x, "maxY": max_y},
        "modelDimensions": {
            "width": MODEL_WIDTH,
            "depth": model_depth,
            "stackHeight": MODEL_STACK_HEIGHT,
            "sheetThickness": MODEL_STACK_HEIGHT / layer_count,
        },
        "simplificationToleranceMeters": SIMPLIFY_TOLERANCE_M,
        "regionBoundaryBlendMeters": REGION_BLEND_M,
        "layers": layer_metadata,
        "regions": [
            {
                "id": name,
                "label": REGION_LABELS[name],
                "maximumSourceElevation": REGION_MAX_ELEVATION[name],
                "lowColor": color_hex((*REGION_PALETTES[name][0], 255)),
                "highColor": color_hex((*REGION_PALETTES[name][1], 255)),
            }
            for name in REGION_ORDER
        ],
        "pins": pin_manifest,
        "profile": profile_metadata,
        "build": {
            "totalVertices": sum(len(mesh.positions) for mesh in layer_meshes),
            "totalTriangles": sum(len(mesh.indices) // 3 for mesh in layer_meshes),
            "glbBytes": inspection["bytes"],
            "nodeCount": inspection["nodes"],
            "meshCount": inspection["meshes"],
            "accessorCount": inspection["accessors"],
            "bufferViewCount": inspection["bufferViews"],
        },
        "sources": {
            "master": str(MASTER_GPKG),
            "registeredLowLayers": str(REGISTERED_GPKG),
            "registrationAudit": str(AUDIT_GPKG),
            "pinSchedule": str(PIN_SCHEDULE),
        },
    }
    OUTPUT_MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(
        f"Wrote {OUTPUT_GLB} ({inspection['bytes']:,} bytes, "
        f"{manifest['build']['totalTriangles']:,} triangles)"
    )
    print(f"Wrote {OUTPUT_MANIFEST}")
    print(f"Wrote {OUTPUT_PROFILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

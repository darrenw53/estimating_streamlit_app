"""DXF utilities for Plate batch import.

Plate-only helper that extracts part sizes and cutting metrics from DXF.

What we compute (per detected part):
  - Bounding box width/length (axis-aligned) in inches
  - True cut perimeter in inches: outer profile + sum(hole perimeters)
  - Hole count
  - Total hole circumference

Nested DXFs (multiple parts in one file) are supported by identifying
multiple outer profiles (closed loops not contained inside any other loop).

We ignore common etch/scribe/text/dimension layers (configurable).

Dependencies: ezdxf, shapely
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Dict, Any, Optional, Tuple

import tempfile

import ezdxf
from ezdxf.path import make_path

from shapely.geometry import Polygon
from shapely.prepared import prep


DEFAULT_IGNORE_LAYER_SUBSTRINGS = [
    "ETCH",
    "SCRIBE",
    "ENGRAVE",
    "MARK",
    "TEXT",
    "DIM",
    "CENTER",
    "CL",
]


@dataclass(frozen=True)
class DetectedPart:
    part_name: str
    bbox_w_in: float
    bbox_l_in: float
    cut_perimeter_in: float
    hole_count: int
    hole_circumference_in: float


def _scale_factor(units: str) -> float:
    u = (units or "in").strip().lower()
    if u in {"mm", "millimeter", "millimeters"}:
        return 1.0 / 25.4
    # Default: inches
    return 1.0


def _layer_is_ignored(layer_name: str, ignore_substrings: Iterable[str]) -> bool:
    name = (layer_name or "").upper()
    for s in ignore_substrings:
        if s and s.upper() in name:
            return True
    return False


def _polygon_from_entity(entity, flatten_tol: float) -> Optional[Polygon]:
    """Try to convert a DXF entity into a closed shapely Polygon.

    We only return polygons for closed geometry. Open paths return None.
    Splines/ellipses are flattened based on flatten_tol.
    """
    try:
        path = make_path(entity)
    except Exception:
        return None

    if path is None:
        return None

    if not getattr(path, "is_closed", False):
        return None

    # Flatten to vertices
    try:
        vertices = list(path.flattening(distance=flatten_tol))
    except Exception:
        return None

    if len(vertices) < 4:
        return None

    coords = [(float(v.x), float(v.y)) for v in vertices]
    # Ensure closed
    if coords[0] != coords[-1]:
        coords.append(coords[0])

    try:
        poly = Polygon(coords)
    except Exception:
        return None

    if not poly.is_valid or poly.area <= 0:
        return None

    return poly


def _collect_closed_polygons(doc, ignore_substrings: Iterable[str], flatten_tol: float) -> List[Polygon]:
    msp = doc.modelspace()
    polys: List[Polygon] = []

    for e in msp:
        # Skip common non-geometry types
        t = e.dxftype()
        if t in {"TEXT", "MTEXT", "DIMENSION", "LEADER", "MLEADER", "HATCH"}:
            continue

        layer = getattr(e.dxf, "layer", "")
        if _layer_is_ignored(layer, ignore_substrings):
            continue

        poly = _polygon_from_entity(e, flatten_tol=flatten_tol)
        if poly is not None:
            polys.append(poly)

    return polys


def _assign_outers_and_holes(polys: List[Polygon]) -> List[Tuple[Polygon, List[Polygon]]]:
    """Return list of (outer_poly, holes[]) for each detected part."""
    if not polys:
        return []

    # Sort by area descending so larger shapes are considered first
    polys_sorted = sorted(polys, key=lambda p: p.area, reverse=True)

    outers: List[Polygon] = []
    for p in polys_sorted:
        # A polygon is an outer profile if it is not contained in an existing outer.
        if not any(o.contains(p) for o in outers):
            outers.append(p)

    # Assign holes to the smallest outer that contains them (usually the correct part)
    outer_prepped = [(o, prep(o)) for o in outers]
    holes_by_outer: Dict[int, List[Polygon]] = {i: [] for i in range(len(outers))}

    for p in polys_sorted:
        # Skip if it's an outer itself
        is_outer = any(p.equals(o) for o in outers)
        if is_outer:
            continue

        containing: List[Tuple[int, float]] = []
        for i, (o, po) in enumerate(outer_prepped):
            try:
                if po.contains(p):
                    containing.append((i, o.area))
            except Exception:
                continue
        if containing:
            # choose smallest area outer that contains p
            containing.sort(key=lambda x: x[1])
            holes_by_outer[containing[0][0]].append(p)

    return [(outers[i], holes_by_outer[i]) for i in range(len(outers))]


def parse_dxf_plate_parts(
    file_bytes: bytes,
    filename: str = "part.dxf",
    units: str = "in",
    ignore_layer_substrings: Optional[List[str]] = None,
    flatten_tol: float = 0.01,
) -> List[DetectedPart]:
    """Parse DXF (bytes) and return detected plate parts.

    Parameters
    ----------
    units:
        "in" or "mm". Output is always inches.
    ignore_layer_substrings:
        List of case-insensitive substrings; entities on layers containing
        any of these are ignored.
    flatten_tol:
        Flattening tolerance used when approximating curves.
    """
    ignore = ignore_layer_substrings or list(DEFAULT_IGNORE_LAYER_SUBSTRINGS)
    sf = _scale_factor(units)

    # ezdxf is most reliable reading from a temporary file
    with tempfile.NamedTemporaryFile(suffix=".dxf", delete=True) as tmp:
        tmp.write(file_bytes)
        tmp.flush()
        doc = ezdxf.readfile(tmp.name)

    polys = _collect_closed_polygons(doc, ignore_substrings=ignore, flatten_tol=flatten_tol)
    groups = _assign_outers_and_holes(polys)

    parts: List[DetectedPart] = []
    base = filename.rsplit(".", 1)[0]

    for idx, (outer, holes) in enumerate(groups, start=1):
        # scale geometry to inches
        outer_s = outer
        holes_s = holes
        if sf != 1.0:
            # shapely scale via manual coordinate scaling
            def _scale_poly(p: Polygon) -> Polygon:
                x, y = p.exterior.coords.xy
                coords = [(xi * sf, yi * sf) for xi, yi in zip(x, y)]
                return Polygon(coords)

            outer_s = _scale_poly(outer)
            holes_s = [_scale_poly(h) for h in holes]

        minx, miny, maxx, maxy = outer_s.bounds
        bbox_w = float(maxx - minx)
        bbox_l = float(maxy - miny)

        outer_perim = float(outer_s.exterior.length)
        hole_perims = [float(h.exterior.length) for h in holes_s]
        hole_circ = float(sum(hole_perims))

        cut_perim = outer_perim + hole_circ
        hole_count = len(holes_s)

        part_name = f"{base} - Part {idx}" if len(groups) > 1 else base

        parts.append(
            DetectedPart(
                part_name=part_name,
                bbox_w_in=round(bbox_w, 3),
                bbox_l_in=round(bbox_l, 3),
                cut_perimeter_in=round(cut_perim, 3),
                hole_count=hole_count,
                hole_circumference_in=round(hole_circ, 3),
            )
        )

    return parts


def parts_to_rows(parts: List[DetectedPart]) -> List[Dict[str, Any]]:
    """Convenience for turning DetectedPart into simple dict rows."""
    rows: List[Dict[str, Any]] = []
    for p in parts:
        rows.append(
            {
                "Part Name": p.part_name,
                "Width (in)": p.bbox_w_in,
                "Length (in)": p.bbox_l_in,
                "True Cut Perimeter (in)": p.cut_perimeter_in,
                "Hole Count": p.hole_count,
                "Total Hole Circumference (in)": p.hole_circumference_in,
            }
        )
    return rows

"""Local GDAL/OSM extraction for the Magnitogorsk notebook. No network calls or data writes."""
from contextlib import contextmanager
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import geopandas as gpd
import pandas as pd
import pyogrio
from shapely import make_valid, union_all


PROJECTED_CRS = "EPSG:32640"
PROMOTED_TAGS = ("building", "building:levels", "building:flats", "building:use", "amenity", "capacity",
                 "name", "operator", "ref", "addr:street", "addr:housenumber")


@contextmanager
def osm_config():
    """Use an independent driver configuration; preserve original tag names and JSON other_tags."""
    default = Path(pyogrio.__file__).parent / "gdal_data" / "osmconf.ini"
    if not default.is_file():
        raise FileNotFoundError(f"Cannot locate GDAL OSM configuration: {default}")
    text = default.read_text(encoding="utf-8")
    text = text.replace("#attribute_name_laundering=no", "attribute_name_laundering=no")
    text = text.replace("#tags_format=json", "tags_format=json")
    section = None
    lines = []
    for line in text.splitlines():
        if line.startswith("["):
            section = line.strip("[]")
        if section in {"points", "multipolygons"} and line.startswith("attributes="):
            tags = list(dict.fromkeys(line.split("=", 1)[1].split(",") + list(PROMOTED_TAGS)))
            line = "attributes=" + ",".join(tags)
        lines.append(line)
    with TemporaryDirectory(prefix="magnitogorsk_osm_") as directory:
        config = Path(directory) / "osmconf.ini"
        config.write_text("\n".join(lines) + "\n", encoding="utf-8")
        yield config


def _restore_tags(frame):
    """Keep the original other_tags JSON and expose relevant tags for BlocksNet."""
    if "other_tags" not in frame:
        return frame
    decoded = []
    for raw in frame.other_tags:
        if raw is None or (not isinstance(raw, (str, dict)) and pd.isna(raw)):
            decoded.append({})
        elif isinstance(raw, dict):
            decoded.append(raw)
        elif isinstance(raw, str):
            tags = json.loads(raw) if raw else {}
            if not isinstance(tags, dict):
                raise ValueError("GDAL other_tags must be a JSON object")
            decoded.append(tags)
        else:
            raise ValueError("Unsupported GDAL other_tags representation")
    for tag in PROMOTED_TAGS:
        values = pd.Series([tags.get(tag) for tags in decoded], index=frame.index)
        if tag not in frame:
            frame[tag] = values
        else:
            frame[tag] = frame[tag].where(frame[tag].notna(), values)
    return frame


def _add_osm_ids(frame, layer):
    """GDAL uses osm_id for relations, osm_way_id for closed ways; do not conflate the namespaces."""
    if "osm_type" in frame and "osm_id" in frame:
        return frame  # Existing normalized cache.
    if "osm_id" not in frame:
        raise ValueError("GDAL returned no OSM identifiers")
    raw_id = frame.osm_id.copy()
    if layer == "points":
        frame["osm_type"] = "node"
    else:
        way_id = frame.get("osm_way_id", pd.Series(None, index=frame.index, dtype=object))
        is_way = way_id.notna() & way_id.astype(str).ne("")
        frame["osm_relation_id"] = raw_id
        frame["osm_type"] = is_way.map({True: "way", False: "relation"})
        frame["osm_id"] = raw_id.where(~is_way, way_id)
    if frame.osm_id.isna().any():
        raise ValueError("An extracted OSM object has no identifier")
    frame["osm_id"] = frame.osm_id.astype(str)
    return frame


def _polygonal(geometry):
    if geometry is None or geometry.is_empty:
        return None
    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return geometry
    if geometry.geom_type == "GeometryCollection":
        pieces = [_polygonal(part) for part in geometry.geoms]
        pieces = [part for part in pieces if part is not None and not part.is_empty]
        return union_all(pieces) if pieces else None
    return None


def _clean_geometry(frame, polygon_only):
    frame = frame.loc[frame.geometry.notna() & ~frame.geometry.is_empty].copy()
    frame["geometry"] = frame.geometry.map(lambda g: g if g.is_valid else make_valid(g))
    if polygon_only:
        # Keep all polygon components of a single OSM object as one MultiPolygon.
        frame["geometry"] = frame.geometry.map(_polygonal)
    else:
        frame = frame.loc[frame.geom_type.isin(["Point", "MultiPoint"])].copy()
    return frame.loc[frame.geometry.notna() & ~frame.geometry.is_empty].copy()


def load_local_osm_objects(kind, data_dir, boundary):
    """Read a cached layer or a tag-filtered local PBF; clip exactly to the city boundary.

    GDAL still scans a regional PBF sequentially. bbox/where limit returned features,
    not necessarily file I/O. Never use max_features for a production extraction.
    """
    if kind not in {"buildings", "schools"}:
        raise ValueError(f"Unsupported local OSM object kind: {kind}")
    data_dir = Path(data_dir)
    if boundary.empty or boundary.crs is None:
        raise ValueError("A nonempty georeferenced city boundary is required")
    if not boundary.geom_type.isin(["Polygon", "MultiPolygon"]).all() or not boundary.is_valid.all():
        raise ValueError("Invalid city boundary")
    mask = boundary.to_crs(PROJECTED_CRS)
    bbox = tuple(boundary.to_crs(4326).total_bounds)
    cache = data_dir / f"{kind}.geojson"
    if cache.is_file():
        raw = gpd.read_file(cache)
        # OSMnx cache IDs may be absent; retain its original columns without fabricating IDs.
        frames = [raw]
    else:
        pbf = data_dir / "ural-fed-district-latest.osm.pbf"
        if not pbf.is_file():
            raise FileNotFoundError(f"Missing local PBF: {pbf}; no network fallback")
        requests = [("multipolygons", "building IS NOT NULL AND building NOT IN ('no', 'false', '0')")]
        if kind == "schools":
            requests = [("multipolygons", "amenity = 'school'"), ("points", "amenity = 'school'")]
        frames = []
        with osm_config() as config:
            for layer, where in requests:
                info = pyogrio.read_info(pbf, layer=layer, CONFIG_FILE=str(config),
                                         force_feature_count=False, force_total_bounds=False)
                required = {"building", "building:levels"} if kind == "buildings" else {"amenity", "capacity"}
                if not required.issubset(info["fields"]):
                    raise ValueError(f"OSM driver did not expose required tags for {layer}: {required}")
                if info["crs"] is None or gpd.GeoSeries([], crs=info["crs"]).crs.to_epsg() != 4326:
                    raise ValueError("OSM driver must report EPSG:4326 for the bbox filter")
                print(f"Local PBF: {kind}, layer={layer}; GDAL may scan the regional file...")
                frame = pyogrio.read_dataframe(pbf, layer=layer, where=where, bbox=bbox,
                                               CONFIG_FILE=str(config), use_arrow=False, on_invalid="raise")
                if not frame.empty:
                    frames.append(_add_osm_ids(frame, layer))
    clipped = []
    for frame in frames:
        if frame.crs is None:
            raise ValueError("OSM layer has no CRS; cannot transform coordinates safely")
        frame = _restore_tags(frame.copy())
        tag = "building" if kind == "buildings" else "amenity"
        if tag not in frame:
            raise ValueError(f"{kind}: missing actual OSM tag {tag}")
        values = frame[tag].astype("string").str.strip().str.lower()
        selected = values.notna() & ~values.isin(["", "no", "false", "0"]) if kind == "buildings" else values.eq("school")
        frame = frame.loc[selected.fillna(False)].copy()
        # Schools can be either actual OSM points or area features.
        polygons = _clean_geometry(frame, polygon_only=True)
        points = _clean_geometry(frame, polygon_only=False) if kind == "schools" else frame.iloc[:0]
        parts = [part for part in [polygons, points] if not part.empty]
        if not parts:
            continue
        frame = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), geometry="geometry", crs=frame.crs)
        frame = frame.to_crs(PROJECTED_CRS)
        frame = gpd.clip(frame, mask)
        # A polygon clipped at a boundary can yield line/point fragments: discard those only.
        if kind == "buildings":
            frame = _clean_geometry(frame, polygon_only=True)
        else:
            area_rows = frame.geom_type.isin(["Polygon", "MultiPolygon", "GeometryCollection"])
            area = _clean_geometry(frame.loc[area_rows], polygon_only=True)
            point = _clean_geometry(frame.loc[~area_rows], polygon_only=False)
            frame = gpd.GeoDataFrame(pd.concat([area, point], ignore_index=True), geometry="geometry", crs=PROJECTED_CRS)
        if not frame.empty:
            clipped.append(frame)
    if not clipped:
        raise ValueError(f"No actual {kind} objects found within the city; no substitute data will be created")
    result = gpd.GeoDataFrame(pd.concat(clipped, ignore_index=True), geometry="geometry", crs=PROJECTED_CRS)
    if {"osm_type", "osm_id"}.issubset(result.columns):
        if result.duplicated(["osm_type", "osm_id"]).any():
            raise ValueError("Duplicate OSM identities after extraction; inspect source data")
    allowed = {"Polygon", "MultiPolygon"} if kind == "buildings" else {"Point", "MultiPoint", "Polygon", "MultiPolygon"}
    if not result.geom_type.isin(allowed).all() or not result.is_valid.all() or result.is_empty.any():
        raise ValueError("Invalid output geometry after OSM extraction")
    print(f"{kind}: {len(result)} actual OSM objects, {result.crs}")
    return result.reset_index(drop=True)

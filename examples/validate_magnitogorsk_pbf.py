"""Quick local PBF reader contract checks. No feature scan or network access."""
import ast
import json
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import pandas as pd
import pyogrio

import magnitogorsk_pbf as reader

DATA = Path(__file__).resolve().parent / "data_magnitogorsk"
PBF = DATA / "ural-fed-district-latest.osm.pbf"

with reader.osm_config() as config:
    for layer in ["multipolygons", "points"]:
        info = pyogrio.read_info(PBF, layer=layer, CONFIG_FILE=str(config),
                                 force_feature_count=False, force_total_bounds=False)
        assert set(reader.PROMOTED_TAGS).issubset(info["fields"])
        assert gpd.GeoSeries([], crs=info["crs"]).crs.to_epsg() == 4326
        print("PASS GDAL configured schema:", layer, info["geometry_type"])

# Identifier/tag unit contracts have no geographical records and are not city data.
ids = pd.DataFrame({"osm_id": [None, "22"], "osm_way_id": ["11", None]})
ids = reader._add_osm_ids(ids, "multipolygons")
assert ids.osm_type.tolist() == ["way", "relation"]
assert ids.osm_id.tolist() == ["11", "22"]
tags = pd.DataFrame({"other_tags": [json.dumps({"building:levels": "3", "capacity": "400"})]})
tags = reader._restore_tags(tags)
assert tags.loc[0, "building:levels"] == "3" and tags.loc[0, "capacity"] == "400"
print("PASS OSM identity namespaces and tag restoration contracts")

# Check repair/clipping on genuine saved geometries without calling them buildings.
water = gpd.read_file(DATA / "water.geojson")
area = water.loc[water.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
clean = reader._clean_geometry(area, polygon_only=True)
assert len(clean) == len(area) and clean.is_valid.all()
boundary = gpd.read_file(DATA / "boundaries.geojson")
clipped = reader._clean_geometry(gpd.clip(clean.to_crs(32640), boundary.to_crs(32640)), polygon_only=True)
assert clipped.geom_type.isin(["Polygon", "MultiPolygon"]).all() and clipped.is_valid.all()
assert clipped.crs.to_epsg() == 32640
print("PASS real Polygon/MultiPolygon repair, retention and city clipping")

# Intercept feature reads; read_info above inspected only metadata of the actual PBF.
empty = gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=4326)
for kind, layers in [("buildings", ["multipolygons"]), ("schools", ["multipolygons", "points"])]:
    if (DATA / f"{kind}.geojson").exists():
        print("SKIP extraction-call contract: existing cache", kind)
        continue
    with patch.object(reader.pyogrio, "read_dataframe", return_value=empty) as read:
        try:
            reader.load_local_osm_objects(kind, DATA, boundary)
        except ValueError as error:
            assert "No actual" in str(error)
        else:
            raise AssertionError("Empty OSM selection must not produce substitute objects")
        assert [call.kwargs["layer"] for call in read.call_args_list] == layers
        for call in read.call_args_list:
            assert call.kwargs["bbox"] == tuple(boundary.to_crs(4326).total_bounds)
            assert "where" in call.kwargs and "CONFIG_FILE" in call.kwargs
            assert "max_features" not in call.kwargs
    print("PASS filtered PBF read contract and empty-result failure:", kind)

notebook = json.loads((DATA.parent / "magnitogorsk_pipeline.ipynb").read_text(encoding="utf-8"))
for index, cell in enumerate(notebook["cells"]):
    if cell["cell_type"] != "code":
        continue
    tree = ast.parse("".join(cell["source"]))
    if index < 19:
        continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            assert node.func.id not in {"network_required", "get_accessibility_graph"}
        if isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"features_from_polygon", "geocode_to_gdf", "urlopen"}
            if isinstance(node.func.value, ast.Name):
                assert node.func.value.id not in {"requests", "httpx", "urllib"}
print("PASS cell syntax and no network branches in sections 7–15")
print("Full regional PBF extraction and city calculations were NOT executed.")

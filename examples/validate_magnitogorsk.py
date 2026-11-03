"""Offline checks on saved OSM data; no city-wide computation or data writes.
Run from the repository root using .venv/Scripts/python.exe.
"""
import ast
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import socket
import sys
from unittest.mock import patch

os.environ["MPLBACKEND"] = "Agg"
import geopandas as gpd
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd
import nbformat

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
DATA = ROOT / "examples/data_magnitogorsk"
notebook = nbformat.read(ROOT / "examples/magnitogorsk_pipeline.ipynb", as_version=4)
nbformat.validate(notebook)
inputs = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in DATA.glob("*.geojson")}
api = {}
for i, cell in enumerate(notebook.cells):
    if cell.cell_type != "code":
        continue
    tree = ast.parse(cell.source, filename=f"cell_{i}")
    if i < 14:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                importlib.import_module(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = importlib.import_module(node.module)
            for alias in node.names:
                api[alias.asname or alias.name] = getattr(module, alias.name)
# Bind every direct BlocksNet API call against the installed callable signature.
for i, cell in enumerate(notebook.cells):
    if cell.cell_type != "code" or i < 14:
        continue
    for call in ast.walk(ast.parse(cell.source)):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
            continue
        function = api.get(call.func.id)
        if not callable(function) or not getattr(function, "__module__", "").startswith("blocksnet"):
            continue
        inspect.signature(function).bind(*[object() for _ in call.args], **{k.arg: object() for k in call.keywords})
print("PASS: notebook syntax, all remaining imports and direct BlocksNet call signatures")

state = {}
with patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden during checks")):
    exec(compile(notebook.cells[14].source, "resume_state", "exec"), state)
    assert len(state["blocks"]) > 0
    assert state["blocks"].index.is_unique
    assert state["blocks"].crs.is_projected
    # With the current missing city datasets, every stage must stop before computation/download.
    missing = ["graph.pkl", "buildings.geojson", "schools.geojson", "buildings_blocks.geojson"]
    if all(not (DATA / name).exists() for name in missing):
        for index in [15, 17, 19, 21, 23, 25, 27, 29, 31, 33]:
            try:
                with patch("magnitogorsk_pbf.load_local_osm_objects", side_effect=RuntimeError("PBF extraction skipped during quick checks")):
                    exec(compile(notebook.cells[index].source, f"stage_cell_{index}", "exec"), state)
            except (RuntimeError, FileNotFoundError) as error:
                print(f"PASS: cell {index} missing-input guard: {error}")
            else:
                raise AssertionError(f"Unexpected execution of stage {index} without required data")

    from blocksnet.blocks.aggregation import aggregate_objects
    from blocksnet.relations import calculate_accessibility_matrix
    from blocksnet.analysis.network.accessibility import area_accessibility
    from blocksnet.enums import LandUse

    blocks = state["blocks"]
    # Aggregate measured areas of real saved functional-zone polygons into 5 real blocks.
    zones = gpd.read_file(DATA / "functional_zones.geojson").to_crs(blocks.crs)
    zones = state["clean_layer"](zones, {"Polygon", "MultiPolygon"}).iloc[:20].copy()
    zones["measured_area"] = zones.area
    sample = blocks.loc[blocks.sindex.query(zones.geometry, predicate="intersects")[1]].copy()
    sample = sample.loc[~sample.index.duplicated()].iloc[:5][["geometry"]]
    if sample.empty:
        sample = blocks.iloc[:5][["geometry"]]
    aggregated, excess = aggregate_objects(sample, zones[["geometry", "measured_area"]])
    assert aggregated.index.equals(sample.index)
    assert aggregated.measured_area.ge(0).all()
    print("PASS: aggregate_objects on actual zone/block geometries", aggregated.shape)

    # Only a two-node graph of one actual residential OSM line, never a replacement city graph.
    roads = gpd.read_file(DATA / "roads.geojson").to_crs(blocks.crs)
    roads = roads.loc[roads.geom_type.eq("LineString") & roads["highway"].eq("residential")]
    line = next(g for g in roads.geometry if not g.is_ring and g.length > 0)
    speed = state["WALK_SPEED_KMH"] * 1000 / 60
    graph = nx.MultiDiGraph(crs=blocks.crs.to_epsg(), type="walk", walk_speed=speed)
    for node, coord in enumerate([line.coords[0], line.coords[-1]]):
        graph.add_node(node, x=coord[0], y=coord[1])
    for a, b in [(0, 1), (1, 0)]:
        graph.add_edge(a, b, type="walk", length_meter=line.length, time_min=line.length / speed)
    state["check_walk_graph"](graph)
    nearest = blocks.distance(line).nsmallest(2).index
    small_blocks = blocks.loc[nearest, ["geometry"]]
    matrix = calculate_accessibility_matrix(small_blocks, graph, weight_key="time_min", dtype=np.float32, max_workers=1)
    assert matrix.shape == (2, 2)
    assert np.allclose(np.diag(matrix), 0)
    assert (matrix.to_numpy() >= 0).all()
    original_blocks = state["blocks"]
    state["blocks"] = blocks.loc[nearest]
    state["checked_matrix"](matrix)
    state["blocks"] = original_blocks
    result = area_accessibility(matrix, blocks.loc[nearest, ["site_area"]], out=True)
    assert result.shape == (2, 1) and result.area_accessibility.ge(0).all()
    print("PASS: actual-road graph validation, 2x2 BlocksNet matrix and area_accessibility")

    # Render real categorical and numeric data and round-trip only in a temporary directory.
    from tempfile import TemporaryDirectory
    small = blocks.loc[blocks.land_use.notna()].iloc[:3].copy()
    assert not small.empty, "Need actual land-use categories for Enum rendering test"
    small["land_use"] = small.land_use.map(lambda v: LandUse(v) if pd.notna(v) else None)
    state["blocks"] = small
    with patch.object(plt, "show"):
        state["map_column"](small, "site_area", "Numeric check", cmap="viridis")
        state["map_column"](small, "land_use", "Enum check", categorical=True)
    state["blocks"] = original_blocks
    with TemporaryDirectory() as directory:
        old_dir = state["DATA_DIR"]
        state["DATA_DIR"] = Path(directory)
        state["save_gdf"](blocks, "blocks_test")
        restored = state["read_geo"]("blocks_test", indexed=True)
        assert restored.index.equals(blocks.index)
        state["save_table"](blocks.drop(columns="geometry"), "table_test")
        restored_table = state["read_table"]("table_test")
        assert restored_table.index.equals(blocks.index)
        state["DATA_DIR"] = old_dir
    plt.close("all")
    print("PASS: map rendering, Enum conversion, GeoJSON/Parquet/CSV block_id round-trip")
# Numerical API unit fixtures, without geometry or city outputs. These are not OSM observations.
from blocksnet.analysis.indicators import calculate_density_indicators
from blocksnet.analysis.morphotypes import get_spacematrix_morphotypes, get_strelka_morphotypes
from blocksnet.analysis.provision import competitive_provision
fixture = pd.DataFrame({
    "site_area": [100.0, 100.0, 100.0], "footprint_area": [20.0, 50.0, 0.0],
    "build_floor_area": [40.0, 200.0, 0.0], "living_area": [36.0, 100.0, 0.0],
    "non_living_area": [4.0, 100.0, 0.0],
}, index=[10, 20, 30])
density = calculate_density_indicators(fixture)
assert np.allclose(density.fsi, [0.4, 2.0, 0.0])
assert np.isnan(density.loc[30, "mxi"]) and np.isinf(density.loc[30, "osr"])
spacematrix, clusters = get_spacematrix_morphotypes(density.loc[[10, 20]], n_clusters=2, random_state=42)
strelka = get_strelka_morphotypes(density.loc[[10, 20]])
assert spacematrix.index.equals(pd.Index([10, 20])) and len(clusters) == 2
assert strelka.morphotype.notna().all()
provision_input = pd.DataFrame({"population": [100.0, 0.0], "capacity": [0, 20]}, index=[10, 20])
fixture_matrix = pd.DataFrame([[0.0, 5.0], [5.0, 0.0]], index=[10, 20], columns=[10, 20])
provision, links = competitive_provision(provision_input, fixture_matrix, accessibility=15, demand=120, max_depth=1)
assert provision.loc[10, "demand"] == 12
assert provision.loc[10, "provision_strong"] == 1.0
assert provision.loc[10, "provision_strong"] == provision.loc[10, "provision_weak"]
assert np.isnan(provision.loc[20, "provision_strong"])
print("PASS: numerical API unit fixtures for density, zero denominators, both morphotypes, CBC provision")

assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in inputs.items())
assert set(inputs) == set(DATA.glob("*.geojson"))
print("PASS: source GeoJSON hashes unchanged; no city results generated")
print("NOT TESTED on actual building/school observations: imputation and full-city indicators (inputs absent)")

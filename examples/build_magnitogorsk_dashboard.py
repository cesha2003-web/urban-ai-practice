r"""Build one offline HTML dashboard from completed Magnitogorsk results.

No network, BlocksNet imports, source changes or model calculations.
Run: .venv\Scripts\python.exe examples\build_magnitogorsk_dashboard.py
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
from enum import Enum
import json
import math
from pathlib import Path

import geopandas as gpd


ROOT = Path(__file__).resolve().parent.parent
LABELS = {
    "block_id": "ID квартала", "land_use": "Использование территории", "site_area": "Площадь квартала, м²",
    "share": "Сумма пересечений преобладающего типа", "residential": "Сумма пересечений: жильё", "business": "Сумма пересечений: деловая",
    "recreation": "Сумма пересечений: рекреация", "industrial": "Сумма пересечений: промышленность", "transport": "Сумма пересечений: транспорт",
    "special": "Сумма пересечений: специальная", "agriculture": "Сумма пересечений: сельское хозяйство",
    "population": "Население, оценка", "footprint_area": "Площадь застройки, м²",
    "build_floor_area": "Поэтажная площадь, м²", "living_area": "Жилая площадь, м²",
    "non_living_area": "Нежилая площадь, м²", "capacity": "Школьные места", "demand": "Спрос на школьные места",
    "demand_within": "Спрос покрыт в нормативе", "demand_without": "Спрос покрыт вне норматива",
    "demand_left": "Неудовлетворённый спрос", "capacity_within": "Места использованы в нормативе",
    "capacity_without": "Места использованы вне норматива", "capacity_left": "Свободные места",
    "provision_strong": "Обеспеченность в нормативе", "provision_weak": "Слабая обеспеченность",
    "fsi": "FSI · плотность застройки", "gsi": "GSI · застроенность", "mxi": "MXI · доля жилья",
    "l": "L · средняя этажность", "osr": "OSR · открытые пространства",
    "share_living": "Жилая / площадь застройки", "share_non_living": "Нежилая / площадь застройки",
    "spacematrix_cluster": "Кластер Spacematrix", "spacematrix_morphotype": "Морфотип Spacematrix",
    "strelka_morphotype": "Морфотип Strelka", "area_accessibility": "Средневзвешенное время, мин",
    "area_accessibility_unreachable": "Недостижимость по площади", "count_buildings": "Объектов зданий",
    "count_schools": "Объектов школ OSM",
}
DESCRIPTIONS = {
    "population": "Оценка из сохранённого расчёта, не официальная статистика населения.",
    "fsi": "Поэтажная площадь / площадь квартала.",
    "gsi": "Площадь застройки / площадь квартала; в BlocksNet ограничена 0…1.",
    "mxi": "Жилая / поэтажная площадь.",
    "l": "Поэтажная площадь / площадь застройки; ограничение функции BlocksNet — не менее 1.",
    "osr": "(Площадь квартала − площадь застройки) / поэтажная площадь.",
    "share_living": "Делитель — площадь застройки. Коэффициент может превышать 1.",
    "share_non_living": "Делитель — площадь застройки. Коэффициент может превышать 1.",
    "provision_strong": "Доля спроса, покрытого в нормативной доступности. При нулевом спросе не определена.",
    "provision_weak": "При max_depth=1 совпадает с обеспеченностью в нормативе.",
    "area_accessibility": "Средневзвешенное по площади время пути до кварталов, минуты. Меньше — быстрее.",
    "count_schools": "Число объектов OSM; точка и территория одной школы могут быть отдельными объектами.",
}


def plain(value):
    if isinstance(value, Enum):
        return plain(value.value)
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "item"):
        return plain(value.item())
    return value


def read_geo(path):
    frame = gpd.read_file(path)
    if frame.empty or frame.crs is None:
        raise ValueError(f"Пустой GeoJSON или отсутствует CRS: {path}")
    if frame.geometry.isna().any() or frame.is_empty.any() or not frame.is_valid.all():
        raise ValueError(f"Есть пустые или невалидные геометрии: {path}. Исправьте исходный результат отдельно")
    return frame


def feature_collection(frame):
    # Only display reprojection. No indicators are computed or modified.
    return plain(json.loads(frame.to_crs(4326).to_json(drop_id=True, na="null")))


def saved_tables(data_dir):
    tables = []
    for filename, title in [
        ("summary.csv", "Сохранённая общегородская сводка"),
        ("spacematrix_clusters.csv", "Центры и интерпретации кластеров Spacematrix"),
        ("provision_links.csv", "Межквартальные связи распределения школьных мест"),
        ("buildings_blocks.csv", "Исходная агрегация зданий по кварталам"),
        ("schools_blocks.csv", "Исходная агрегация школ по кварталам"),
    ]:
        path = data_dir / filename
        if path.is_file():
            with path.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                columns = [k for k in (reader.fieldnames or []) if k not in {"", "Unnamed: 0"}]
                records = [{k: row.get(k, "") for k in columns} for row in reader]
            tables.append({"title": title, "source": filename, "columns": columns, "rows": records})
    return tables


def saved_matrix(data_dir, block_ids):
    path = data_dir / "accessibility_matrix.csv"
    if not path.is_file():
        raise FileNotFoundError(f"Для --include-matrix нужен готовый CSV: {path}")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        header = next(reader)
        ids = header[1:]
        expected = {str(value) for value in block_ids}
        if len(ids) != len(set(ids)) or set(ids) != expected:
            raise ValueError("Идентификаторы матрицы не соответствуют results_blocks.geojson")
        rows = {}
        for record in reader:
            if not record:
                continue
            if len(record) != len(ids) + 1 or record[0] in rows:
                raise ValueError("Некорректная строка сохранённой матрицы")
            values = []
            for cell in record[1:]:
                value = float(cell) if cell.strip() else math.nan
                if value < 0:
                    raise ValueError("Отрицательное время в сохранённой матрице")
                values.append(value if math.isfinite(value) else "Infinity" if value == math.inf else None)
            rows[record[0]] = values
        if set(rows) != expected:
            raise ValueError("Неполный набор строк сохранённой матрицы")
    return {"ids": ids, "rows": rows, "source": path.name}


def load_results(data_dir, include_matrix=False):
    source = data_dir / "results_blocks.geojson"
    if not source.is_file():
        raise FileNotFoundError(f"Нет готового итогового слоя: {source}")
    blocks = read_geo(source)
    if "block_id" not in blocks or blocks.block_id.isna().any() or not blocks.block_id.is_unique:
        raise ValueError("В results_blocks.geojson нужны уникальные непустые block_id")
    if not blocks.geom_type.isin(["Polygon", "MultiPolygon"]).all():
        raise ValueError("Итоговые кварталы должны иметь тип Polygon/MultiPolygon")
    sources = [source.name]
    # Join only saved counts, without spatial aggregation or overwriting existing indicators.
    for filename, target in [("buildings_blocks.geojson", "count_buildings"), ("schools_blocks.geojson", "count_schools")]:
        path = data_dir / filename
        if path.is_file() and target not in blocks:
            extra = gpd.read_file(path)
            if "count" in extra and "block_id" in extra:
                if not extra.block_id.is_unique or set(extra.block_id) != set(blocks.block_id):
                    raise ValueError(f"Идентификаторы в {filename} не соответствуют итоговому слою")
                blocks[target] = blocks.block_id.map(extra.set_index("block_id")["count"])
                sources.append(filename)
    optional = {}
    for key, filename in [("boundary", "boundaries.geojson"), ("schools", "schools.geojson")]:
        path = data_dir / filename
        optional[key] = feature_collection(read_geo(path)) if path.is_file() else None
        if path.is_file():
            sources.append(filename)
    metadata = {}
    path = data_dir / "run_meta.json"
    if path.is_file():
        metadata = plain(json.loads(path.read_text(encoding="utf-8")))
        sources.append(path.name)
    graph_meta = data_dir / "graph_meta.json"
    if graph_meta.is_file():
        metadata["graph_meta"] = plain(json.loads(graph_meta.read_text(encoding="utf-8")))
        sources.append(graph_meta.name)
    tables = saved_tables(data_dir)
    sources.extend(table["source"] for table in tables)
    matrix = saved_matrix(data_dir, blocks.block_id.tolist()) if include_matrix else None
    if matrix is not None:
        sources.append(matrix["source"])
    return {
        "saved_tables": tables, "matrix": matrix,
        "blocks": feature_collection(blocks), **optional, "metadata": metadata,
        "labels": LABELS, "descriptions": DESCRIPTIONS, "sources": sources,
        "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def main():
    parser = argparse.ArgumentParser(description="Один автономный HTML из готовых результатов Магнитогорска")
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parent / "data_magnitogorsk")
    parser.add_argument("--output", type=Path, default=ROOT / "dashboard.html")
    parser.add_argument("--include-matrix", action="store_true", help="Встроить готовую матрицу CSV: HTML будет существенно больше")
    args = parser.parse_args()
    if args.output.suffix.lower() != ".html":
        parser.error("Выходной файл должен иметь расширение .html")
    payload = load_results(args.data_dir.resolve(), include_matrix=args.include_matrix)
    serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    serialized = serialized.replace(chr(60), chr(92) + "u003c").replace(chr(0x2028), chr(92) + "u2028").replace(chr(0x2029), chr(92) + "u2029")
    document = HTML_TEMPLATE.replace("__DASHBOARD_PAYLOAD__", serialized)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")
    print(f"Готово: {output}")
    print(f"Кварталов: {len(payload['blocks']['features'])}. Файл открывается в браузере без интернета.")


HTML_TEMPLATE = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Магнитогорск · кварталы и городская среда</title>
<style>
:root{--ink:#172e38;--muted:#61747d;--line:#dbe5e7;--paper:#f2f6f5;--teal:#087f82;--accent:#e3b66b}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:14px/1.5 Segoe UI,system-ui,sans-serif}header{background:#132e38;color:#fff;padding:25px max(24px,calc((100vw - 1500px)/2));border-bottom:4px solid var(--accent)}header .eyebrow{letter-spacing:.18em;text-transform:uppercase;font-size:11px;color:#a7c6cb}h1{font-size:clamp(25px,4vw,38px);margin:6px 0;font-weight:650;letter-spacing:-.03em}header p{margin:0;color:#bbd0d3;max-width:900px}main{max-width:1548px;margin:auto;padding:24px}.badge{display:inline-block;background:#254852;color:#d1e9e6;border-radius:20px;padding:3px 12px;margin-top:12px;font-size:12px}.cards{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:20px}.card,.panel{background:#fff;border:1px solid var(--line);border-radius:12px}.card{padding:16px}.card span{display:block;color:var(--muted);font-size:12px}.card strong{font-size:25px;display:block;letter-spacing:-.03em}.card small{color:var(--muted);font-size:11px}.toolbar{display:flex;gap:14px;align-items:end;flex-wrap:wrap;padding:16px;margin-bottom:16px}.field{display:flex;flex-direction:column;gap:5px;min-width:180px}.field.grow{flex:1}label,.label{font-size:12px;color:var(--muted)}input,select,button{font:inherit;color:var(--ink);border:1px solid #cbd9dd;border-radius:7px;padding:9px 11px;background:#fff}select{max-width:100%}input:focus,select:focus,button:focus-visible{outline:3px solid #8dc7c5;outline-offset:1px}button{cursor:pointer}button:hover{background:#edf6f5}button.primary{background:var(--teal);color:#fff;border-color:var(--teal)}.layout{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:16px}.panel h2{font-size:17px;margin:0}.panel-head{padding:16px 18px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:12px;align-items:center}.subtle{color:var(--muted);font-size:12px}.map-wrap{position:relative;background:#eaf0ee;border-radius:0 0 12px 12px;overflow:hidden}#map{display:block;width:100%;height:560px;touch-action:none;cursor:grab;background:radial-gradient(ellipse at center,#f7faf6,#e1ece9)}#map:active{cursor:grabbing}.map-controls{position:absolute;top:12px;left:12px;display:flex;gap:5px;z-index:2}.map-controls button{box-shadow:0 2px 8px #172e3812;background:white}.map-note{position:absolute;bottom:9px;left:12px;right:12px;pointer-events:none;font-size:11px;color:#42626c;background:#ffffffdf;padding:3px 8px;border-radius:4px}.quarter{stroke:#fff;stroke-width:.6;vector-effect:non-scaling-stroke;cursor:pointer}.quarter:hover{stroke:#132e38;stroke-width:1.7}.quarter.selected{stroke:#f17b39;stroke-width:3;paint-order:fill stroke}.quarter.filtered{display:none}.boundary{fill:none;stroke:#244652;stroke-width:1.6;stroke-dasharray:5 3;vector-effect:non-scaling-stroke;pointer-events:none}.school{fill:#f2b24c;stroke:#5a401a;stroke-width:1;vector-effect:non-scaling-stroke}.legend{padding:14px 18px;max-height:195px;overflow:auto}.legend-item{display:flex;align-items:center;gap:8px;margin:3px 0;font-size:12px}.swatch{width:15px;height:12px;border-radius:3px;display:inline-block;flex:none}.details{max-height:540px;overflow:auto;padding:0 16px 12px}.details dl{margin:0}.details dt{font-size:11px;color:var(--muted);padding-top:8px}.details dd{margin:0;border-bottom:1px solid #edf1f2;padding:0 0 5px;overflow-wrap:anywhere}.charts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-top:18px}.chart{padding:14px 16px;min-height:290px;overflow:auto}.chart h2{font-size:15px;margin-bottom:3px}.chart svg{display:block;width:100%;min-width:240px}.bar-row{display:grid;grid-template-columns:135px 1fr 30px;align-items:center;gap:7px;font-size:11px;margin:7px 0}.bar-track{background:#eaf1f0;border-radius:3px;overflow:hidden}.bar{height:10px;background:#168e8c;border-radius:3px}.bar-label{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.section{margin-top:20px}.table-wrap{overflow:auto;max-height:510px}table{border-collapse:collapse;width:100%;font-size:12px;white-space:nowrap}th,td{padding:9px 12px;text-align:right;border-bottom:1px solid #e8edef}th{position:sticky;top:0;background:#f4f8f8;color:#405e68;cursor:pointer;z-index:1}th:first-child,td:first-child{text-align:left;position:sticky;left:0;background:#f7fafa}th:first-child{z-index:3}tr:hover td{background:#e9f6f3;cursor:pointer}tr.active td{background:#fff1d9}.pager{display:flex;gap:10px;align-items:center;justify-content:flex-end;padding:12px}.summary td{white-space:normal}.insights{padding:18px 24px}.insights li{margin:9px 0}.meta{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.5 Consolas,monospace;background:#f6f9f8;padding:16px;border-radius:6px}footer{padding:22px 0;color:var(--muted);font-size:12px}.tip{position:fixed;display:none;z-index:10;pointer-events:none;background:#16343def;color:white;border-radius:7px;padding:8px 12px;font-size:12px;max-width:300px}.empty{padding:25px;color:var(--muted)}.axis{font-size:10px;fill:#687e86}.grid{stroke:#dfe8e9;stroke-width:1}details>summary{cursor:pointer;padding:14px 18px}.note{padding:0 18px 14px}.chart-controls{display:flex;gap:8px;margin:7px 0}.chart-controls select{font-size:11px;padding:5px;width:50%}@media(max-width:1150px){.cards{grid-template-columns:repeat(3,1fr)}.layout{grid-template-columns:minmax(0,1fr) 285px}.charts{grid-template-columns:1fr 1fr}.charts .chart:last-child{grid-column:1/-1}}@media(max-width:760px){main{padding:12px}.cards{grid-template-columns:repeat(2,1fr)}.layout,.charts{grid-template-columns:1fr}.charts .chart:last-child{grid-column:auto}#map{height:430px}.field{width:100%;min-width:0}.toolbar{align-items:stretch}.details{max-height:300px}header{padding:20px}.card strong{font-size:22px}.panel-head{flex-wrap:wrap}}
</style></head><body>
<header><div class="eyebrow">Исследование территории · BlocksNet 1.0.0a9</div><h1>Магнитогорск: город по кварталам</h1><p>Готовые результаты исследования: застройка, население, школьная обеспеченность, морфотипы и пешеходная доступность.</p><div class="badge">Автономный HTML · OpenStreetMap · без повторного расчёта</div></header>
<main>
<div id="cards" class="cards" aria-live="polite"></div>
<div class="panel toolbar"><div class="field grow"><label for="metric">Показатель на карте</label><select id="metric"></select></div><div class="field"><label for="landuse">Использование территории</label><select id="landuse"></select></div><div class="field grow"><label for="search">Поиск по всем значениям таблицы</label><input id="search" type="search" placeholder="ID, морфотип или другое значение"></div><button id="reset">Сбросить</button><button id="download" class="primary">CSV выборки</button></div>
<div class="layout"><section class="panel"><div class="panel-head"><div><h2 id="mapTitle">Карта кварталов</h2><div class="subtle" id="metricDescription"></div></div><label><input type="checkbox" id="showSchools"> Объекты школ</label></div><div class="map-wrap"><div class="map-controls"><button id="zoomIn" aria-label="Приблизить">+</button><button id="zoomOut" aria-label="Отдалить">−</button><button id="home">Весь город</button></div><svg id="map" viewBox="0 0 1000 650" role="img" aria-label="Интерактивная карта кварталов Магнитогорска"><g id="viewport"><g id="quarters"></g><g id="boundary"></g><g id="schools" visibility="hidden"></g></g></svg><div class="map-note">Перетаскивание — панорама · колесо — масштаб · щелчок — показатели квартала. Подложка не загружается.</div></div><div class="legend" id="legend"></div></section>
<aside class="panel"><div class="panel-head"><h2 id="detailTitle">Выберите квартал</h2></div><div class="details" id="details"><p class="subtle">Щёлкните квартал на карте или строку таблицы. Здесь появятся все его сохранённые показатели.</p></div></aside></div>
<div class="charts"><section class="panel chart"><h2 id="distributionTitle">Распределение</h2><div id="distribution"></div></section><section class="panel chart"><h2>Морфотипы кварталов</h2><select id="morphology" aria-label="Метод классификации"><option value="spacematrix_morphotype">Spacematrix</option><option value="strelka_morphotype">Strelka</option></select><div id="morphChart"></div></section><section class="panel chart"><h2>Сопоставление показателей</h2><div class="chart-controls"><select id="scatterX" aria-label="Показатель оси X"></select><select id="scatterY" aria-label="Показатель оси Y"></select></div><div id="scatter"></div></section></div>
<section class="panel section"><div class="panel-head"><div><h2>Все показатели кварталов</h2><div class="subtle" id="tableStatus"></div></div><span class="subtle">Заголовок столбца — сортировка · строка — выбор квартала</span></div><div class="table-wrap"><table id="table"><thead></thead><tbody></tbody></table></div><div class="pager"><button id="prev">←</button><span id="pageStatus"></span><button id="next">→</button></div></section>
<section class="panel section"><div class="panel-head"><h2>Сводка числовых показателей</h2><span class="subtle">По текущей выборке; отсутствующие значения исключены</span></div><div class="table-wrap"><table class="summary" id="summary"><thead><tr><th>Показатель</th><th>Заполнено</th><th>Нет значения</th><th>Минимум</th><th>Медиана</th><th>Среднее</th><th>Максимум</th></tr></thead><tbody></tbody></table></div></section>
<section class="panel section"><div class="panel-head"><h2>Контроль сохранённых данных</h2></div><div class="insights" id="quality"></div></section>
<details class="panel section"><summary>Сохранённая матрица времени в пути</summary><div class="note"><p id="matrixNote"></p><div id="matrixControls" class="toolbar"><div class="field"><label for="matrixFrom">Из квартала</label><select id="matrixFrom"></select></div><div class="field"><label for="matrixTo">В квартал</label><select id="matrixTo"></select></div><strong id="matrixValue"></strong></div><div class="table-wrap"><table id="matrixTable"><thead><tr><th>Квартал назначения</th><th>Время, мин</th></tr></thead><tbody></tbody></table></div></div></details>
<section id="savedTables" class="section"></section>
<section class="panel section"><div class="panel-head"><h2>Что показывают сохранённые результаты</h2><span class="subtle">Выводы обновляются при фильтрации</span></div><div class="insights" id="insights"></div></section>
<details class="panel section"><summary>Методика, источники и паспорт расчёта</summary><div class="note"><p>Показатели прочитаны из готовых файлов. На странице выполняются только сортировка, фильтрация и описательная сводка сохранённых значений. BlocksNet, маршрутизация, восстановление населения и классификация повторно не запускаются.</p><p>Население оценочное; этажность и ёмкость школ могли быть заполнены нормативами. Нулевой спрос и деление на ноль могут давать неопределённые показатели. Серый цвет означает отсутствие значения. Объекты школ OSM не всегда соответствуют уникальным учреждениям. Сводка по отфильтрованным кварталам не является новым расчётом обеспеченности: исходное распределение спроса остаётся общегородским.</p><p>Карта использует встроенные геометрии без тайлов и внешних библиотек. Средневзвешенное время — сохранённый показатель доступности между кварталами. Высокие и низкие значения описывают результат модели, а не устанавливают причину.</p><div id="sources" class="subtle"></div><pre id="metadata" class="meta"></pre></div></details>
<footer>© OpenStreetMap contributors · Данные OSM, ODbL. Магнитогорск · учебное исследование. Один локальный файл, без CDN, шрифтов и сетевых запросов.</footer></main><div class="tip" id="tip"></div>
<script id="payload" type="application/json">__DASHBOARD_PAYLOAD__</script><script>
"use strict";
const D=JSON.parse(document.getElementById('payload').textContent);
const $=id=>document.getElementById(id), NS='http://www.w3.org/2000/svg';
const features=D.blocks.features, rows=features.map(f=>f.properties);
const fields=[...new Set(rows.flatMap(Object.keys))];
fields.sort((a,b)=>a==='block_id'?-1:b==='block_id'?1:0);
const finite=v=>typeof v==='number'&&Number.isFinite(v);
const cats=new Set(['land_use','spacematrix_cluster','spacematrix_morphotype','strelka_morphotype','area_accessibility_unreachable']);
const knownNumbers=new Set(['site_area','share','residential','business','recreation','industrial','transport','special','agriculture','population','footprint_area','build_floor_area','living_area','non_living_area','capacity','demand','demand_within','demand_without','demand_left','capacity_within','capacity_without','capacity_left','provision_strong','provision_weak','fsi','gsi','mxi','l','osr','share_living','share_non_living','area_accessibility','count_buildings','count_schools']);
const nums=fields.filter(k=>k!=='block_id'&&!cats.has(k)&&(knownNumbers.has(k)||rows.some(r=>finite(r[k]))));
const label=k=>D.labels[k]||k;
const nf=new Intl.NumberFormat('ru-RU',{maximumFractionDigits:3});
const sf=new Intl.NumberFormat('ru-RU',{notation:'compact',maximumFractionDigits:1});
const esc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const landNames={residential:'Жилая',business:'Деловая',recreation:'Рекреационная',industrial:'Промышленная',transport:'Транспортная',special:'Специальная',agriculture:'Сельскохозяйственная'};
function valueText(v,k){if(v===null||v===undefined)return '—';if(finite(v))return nf.format(v);if(typeof v==='boolean')return v?'Да':'Нет';if(k==='land_use')return landNames[v]||String(v);return typeof v==='object'?JSON.stringify(v):String(v)}
const number=v=>finite(v)?nf.format(v):'—';
const pct=v=>finite(v)?nf.format(v*100)+'%':'—';
const palette=['#cfe7df','#94cfc5','#4baca6','#13898d','#075865'];
const categoryPalette=['#168b8b','#dbac63','#697da6','#b15f66','#7da376','#976b99','#577f8a','#ca916d','#8d9448','#637b56','#9b9b9b','#685e91'];
let filtered=rows.map((_,i)=>i), metric='fsi', selected=null, page=0, sortKey='block_id', sortDir=1;
const pageSize=50, paths=[], camera={x:0,y:0,z:1};let categoryColor=new Map();
function option(select,value,text){select.add(new Option(text,value))}
fields.filter(k=>k!=='block_id').forEach(k=>option($('metric'),k,label(k)));
metric=fields.includes('fsi')?'fsi':fields.find(k=>k!=='block_id');$('metric').value=metric;
option($('landuse'),'','Все территории');option($('landuse'),'__null__','Не определено');
[...new Set(rows.map(r=>r.land_use).filter(v=>v!==null&&v!==undefined))].sort().forEach(v=>option($('landuse'),String(v),landNames[v]||String(v)));
for(const k of nums){option($('scatterX'),k,label(k));option($('scatterY'),k,label(k))}
$('scatterX').value=nums.includes('fsi')?'fsi':nums[0];$('scatterY').value=nums.includes('l')?'l':nums[1]||nums[0];
function coordinates(geometry,visit){if(!geometry)return;if(geometry.type==='GeometryCollection'){geometry.geometries.forEach(g=>coordinates(g,visit));return}function walk(a){if(typeof a[0]==='number'){visit(a);return}a.forEach(walk)}walk(geometry.coordinates)}
function mercator(c){const lat=Math.max(-85,Math.min(85,c[1]))*Math.PI/180;return [c[0]*Math.PI/180,Math.log(Math.tan(Math.PI/4+lat/2))]}
let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
for(const f of features)coordinates(f.geometry,c=>{const [x,y]=mercator(c);minX=Math.min(minX,x);maxX=Math.max(maxX,x);minY=Math.min(minY,y);maxY=Math.max(maxY,y)});
const scale=Math.min(950/Math.max(maxX-minX,1e-12),590/Math.max(maxY-minY,1e-12));
const offsetX=(1000-(maxX-minX)*scale)/2,offsetY=(650-(maxY-minY)*scale)/2;
function project(c){const [x,y]=mercator(c);return [offsetX+(x-minX)*scale,offsetY+(maxY-y)*scale]}
function linePath(points,closed){return points.map((c,i)=>{const [x,y]=project(c);return (i?'L':'M')+x.toFixed(2)+' '+y.toFixed(2)}).join(' ')+(closed?' Z':'')}
function geometryPath(g){if(!g)return '';switch(g.type){case 'Polygon':return g.coordinates.map(r=>linePath(r,true)).join(' ');case 'MultiPolygon':return g.coordinates.flatMap(p=>p.map(r=>linePath(r,true))).join(' ');case 'LineString':return linePath(g.coordinates,false);case 'MultiLineString':return g.coordinates.map(r=>linePath(r,false)).join(' ');case 'GeometryCollection':return g.geometries.map(geometryPath).join(' ');default:return ''}}
function svg(tag,attrs){const el=document.createElementNS(NS,tag);for(const [k,v]of Object.entries(attrs||{}))el.setAttribute(k,v);return el}
for(let i=0;i<features.length;i++){const el=svg('path',{d:geometryPath(features[i].geometry),class:'quarter','fill-rule':'evenodd','data-index':i});$('quarters').appendChild(el);paths.push(el)}
if(D.boundary)for(const f of D.boundary.features)$('boundary').appendChild(svg('path',{d:geometryPath(f.geometry),class:'boundary','fill-rule':'evenodd'}));
if(D.schools)for(const f of D.schools.features){let el;if(f.geometry.type==='Point'){const [cx,cy]=project(f.geometry.coordinates);el=svg('circle',{cx,cy,r:3,class:'school'})}else if(f.geometry.type==='MultiPoint'){for(const c of f.geometry.coordinates){const [cx,cy]=project(c);$('schools').appendChild(svg('circle',{cx,cy,r:3,class:'school'}))}continue}else el=svg('path',{d:geometryPath(f.geometry),class:'school','fill-rule':'evenodd'});const title=svg('title');title.textContent=(f.properties.name||'Объект школы')+' · мест: '+valueText(f.properties.capacity,'capacity');el.appendChild(title);$('schools').appendChild(el)}
function applyCamera(){$('viewport').setAttribute('transform',`translate(${camera.x} ${camera.y}) scale(${camera.z})`)}
function svgPoint(event){const p=$('map').createSVGPoint();p.x=event.clientX;p.y=event.clientY;return p.matrixTransform($('map').getScreenCTM().inverse())}
function zoom(factor,x=500,y=325){const old=camera.z,next=Math.max(.6,Math.min(35,old*factor)),ratio=next/old;camera.x=x-(x-camera.x)*ratio;camera.y=y-(y-camera.y)*ratio;camera.z=next;applyCamera()}
$('map').addEventListener('wheel',e=>{e.preventDefault();const p=svgPoint(e);zoom(e.deltaY<0?1.18:1/1.18,p.x,p.y)},{passive:false});
$('zoomIn').onclick=()=>zoom(1.5);$('zoomOut').onclick=()=>zoom(1/1.5);$('home').onclick=()=>{Object.assign(camera,{x:0,y:0,z:1});applyCamera()};
let drag=null;
$('map').addEventListener('pointerdown',e=>{if(e.button!==0)return;const p=svgPoint(e);drag={id:e.pointerId,x:p.x,y:p.y,oldX:camera.x,oldY:camera.y,clientX:e.clientX,clientY:e.clientY,index:e.target.closest('.quarter')?.dataset.index,moved:false};$('map').setPointerCapture(e.pointerId);$('tip').style.display='none'});
$('map').addEventListener('pointermove',e=>{if(drag&&e.pointerId===drag.id){const p=svgPoint(e);if(Math.hypot(e.clientX-drag.clientX,e.clientY-drag.clientY)>4)drag.moved=true;if(drag.moved){camera.x=drag.oldX+p.x-drag.x;camera.y=drag.oldY+p.y-drag.y;applyCamera()}return}const index=e.target.closest('.quarter')?.dataset.index;if(index!==undefined){const r=rows[+index];showTip(e,'Квартал '+r.block_id+' · '+label(metric)+': '+valueText(r[metric],metric))}else $('tip').style.display='none'});
$('map').addEventListener('pointerup',e=>{if(drag&&e.pointerId===drag.id){if(!drag.moved&&drag.index!==undefined)selectRow(+drag.index,false);drag=null}});
$('map').addEventListener('pointercancel',()=>{drag=null});$('map').addEventListener('pointerleave',()=>{$('tip').style.display='none'});
function showTip(e,text){const tip=$('tip');tip.textContent=text;tip.style.display='block';tip.style.left=Math.max(8,Math.min(window.innerWidth-310,e.clientX+14))+'px';tip.style.top=Math.max(8,Math.min(window.innerHeight-70,e.clientY+12))+'px'}
$('showSchools').onchange=()=>{$('schools').setAttribute('visibility',$('showSchools').checked?'visible':'hidden')};
function selectRow(index,focus){if(selected!==null)paths[selected].classList.remove('selected');selected=index;paths[index].classList.add('selected');paths[index].parentNode.appendChild(paths[index]);const r=rows[index];$('detailTitle').textContent='Квартал № '+r.block_id;$('details').innerHTML='<dl>'+fields.map(k=>'<dt>'+esc(label(k))+' <span class="subtle">('+esc(k)+')</span></dt><dd>'+esc(valueText(r[k],k))+'</dd>').join('')+'</dl>';if(focus){const b=paths[index].getBBox();const z=Math.min(24,Math.max(1,Math.min(700/Math.max(b.width,1),420/Math.max(b.height,1))));Object.assign(camera,{z,x:500-(b.x+b.width/2)*z,y:325-(b.y+b.height/2)*z});applyCamera()}const at=sortedRows().indexOf(index);if(at>=0)page=Math.floor(at/pageSize);renderTable()}
function numeric(k){return nums.includes(k)}
function values(k){return filtered.map(i=>rows[i][k]).filter(finite)}
function quantile(sorted,q){if(!sorted.length)return null;const p=(sorted.length-1)*q,l=Math.floor(p),r=p-l;return sorted[l]+((sorted[l+1]??sorted[l])-sorted[l])*r}
function sum(k){const v=values(k);return v.length?v.reduce((a,b)=>a+b,0):null}
function distribution(k){const counts=new Map();for(const i of filtered){const value=rows[i][k];const key=value===null||value===undefined?'—':String(value);counts.set(key,(counts.get(key)||0)+1)}return [...counts].sort((a,b)=>b[1]-a[1])}
function renderMap(){const active=new Set(filtered);let color,legend='';if(numeric(metric)){const sorted=values(metric).sort((a,b)=>a-b);const cuts=[.2,.4,.6,.8].map(q=>quantile(sorted,q));color=v=>{if(!finite(v)||!sorted.length)return '#bac5c8';let j=0;while(j<cuts.length&&v>cuts[j])j++;return palette[j]};if(sorted.length){if(sorted[0]===sorted.at(-1)){legend='<div class="legend-item"><i class="swatch" style="background:'+palette[0]+'"></i>'+esc(number(sorted[0]))+'</div>'}else{const edges=[sorted[0],...cuts,sorted.at(-1)];legend=palette.map((c,i)=>'<div class="legend-item"><i class="swatch" style="background:'+c+'"></i>'+esc(number(edges[i]))+' … '+esc(number(edges[i+1]))+'</div>').join('');legend+='<div class="subtle">Пять групп по квантилям текущей выборки</div>'}}}else{const categories=distribution(metric).filter(([k])=>k!=='—');categoryColor=new Map(categories.map(([k],i)=>[k,categoryPalette[i%categoryPalette.length]]));color=v=>v===null||v===undefined?'#bac5c8':categoryColor.get(String(v))||'#bac5c8';legend=categories.map(([k,n])=>'<div class="legend-item"><i class="swatch" style="background:'+categoryColor.get(k)+'"></i>'+esc(valueText(rows[filtered.find(i=>String(rows[i][metric])===k)]?.[metric]??k,metric))+' · '+n+'</div>').join('')}
for(let i=0;i<paths.length;i++){paths[i].classList.toggle('filtered',!active.has(i));paths[i].setAttribute('fill',color(rows[i][metric]))}
$('mapTitle').textContent=label(metric);$('metricDescription').textContent=D.descriptions[metric]||'Сохранённый показатель · '+metric;$('legend').innerHTML=legend+'<div class="legend-item"><i class="swatch" style="background:#bac5c8"></i>Нет значения / не определено</div>'}
function renderCards(){const den=sum('demand'),covered=sum('demand_within'),times=values('area_accessibility').sort((a,b)=>a-b);const items=[['Кварталов',number(filtered.length),'из '+number(rows.length)],['Население',number(sum('population')),'оценка по сохранённым данным'],['Мест в школах',number(sum('capacity')),'ёмкость объектов OSM'],['Спрос покрыт',pct(den>0&&covered!==null?covered/den:null),'в пределах норматива; взвешено спросом'],['Доступность, медиана',number(quantile(times,.5)),'минут · только конечные значения'],['Площадь кварталов',number(sum('site_area')===null?null:sum('site_area')/1e6),'км² · сумма площадей выборки']];$('cards').innerHTML=items.map(([a,b,c])=>'<div class="card"><span>'+esc(a)+'</span><strong>'+esc(b)+'</strong><small>'+esc(c)+'</small></div>').join('')}
function sortedRows(){return [...filtered].sort((a,b)=>{const x=rows[a][sortKey],y=rows[b][sortKey];if(x===null||x===undefined)return y===null||y===undefined?0:1;if(y===null||y===undefined)return -1;const d=finite(x)&&finite(y)?x-y:String(x).localeCompare(String(y),'ru',{numeric:true});return d*sortDir})}
function renderTable(){const ordered=sortedRows(),pages=Math.max(1,Math.ceil(ordered.length/pageSize));page=Math.max(0,Math.min(page,pages-1));$('table').tHead.innerHTML='<tr>'+fields.map(k=>'<th><button type="button" data-key="'+esc(k)+'" title="'+esc(k)+'">'+esc(label(k))+(k===sortKey?(sortDir===1?' ↑':' ↓'):'')+'</button></th>').join('')+'</tr>';$('table').tBodies[0].innerHTML=ordered.slice(page*pageSize,(page+1)*pageSize).map(i=>'<tr data-index="'+i+'" class="'+(selected===i?'active':'')+'">'+fields.map(k=>'<td title="'+esc(valueText(rows[i][k],k))+'">'+esc(valueText(rows[i][k],k))+'</td>').join('')+'</tr>').join('');$('tableStatus').textContent=number(filtered.length)+' кварталов · '+fields.length+' столбцов · геометрии не включены в CSV';$('pageStatus').textContent=(page+1)+' / '+pages;$('prev').disabled=page===0;$('next').disabled=page>=pages-1}
$('table').tHead.onclick=e=>{const b=e.target.closest('[data-key]');if(!b)return;const k=b.dataset.key;sortDir=k===sortKey?-sortDir:1;sortKey=k;page=0;renderTable()};$('table').tBodies[0].onclick=e=>{const tr=e.target.closest('[data-index]');if(tr)selectRow(+tr.dataset.index,true)};$('prev').onclick=()=>{page--;renderTable()};$('next').onclick=()=>{page++;renderTable()};
function renderSummary(){$('summary').tBodies[0].innerHTML=nums.map(k=>{const a=values(k).sort((a,b)=>a-b),mean=a.length?a.reduce((x,y)=>x+y,0)/a.length:null;return '<tr><td>'+esc(label(k))+' <span class="subtle">'+esc(k)+'</span></td><td>'+a.length+'</td><td>'+(filtered.length-a.length)+'</td><td>'+esc(number(a[0]))+'</td><td>'+esc(number(quantile(a,.5)))+'</td><td>'+esc(number(mean))+'</td><td>'+esc(number(a.at(-1)))+'</td></tr>'}).join('')}

function bars(element,entries,k){if(!entries.length){element.innerHTML='<p class="empty">Нет данных в выборке</p>';return}const max=Math.max(...entries.map(v=>v[1]),1);element.innerHTML='<div style="max-height:235px;overflow:auto">'+entries.map(([v,n],i)=>{const text=v==='—'?'Не определено':valueText(v,k);return '<div class="bar-row" title="'+esc(text+': '+n)+'"><span class="bar-label">'+esc(text)+'</span><div class="bar-track"><div class="bar" style="width:'+(n/max*100)+'%;background:'+categoryPalette[i%categoryPalette.length]+'"></div></div><span>'+n+'</span></div>'}).join('')+'</div>'}
function histogram(){const element=$('distribution');$('distributionTitle').textContent='Распределение · '+label(metric);if(!numeric(metric)){bars(element,distribution(metric),metric);return}const a=values(metric);if(!a.length){element.innerHTML='<p class="empty">Нет числовых значений</p>';return}const lo=Math.min(...a),hi=Math.max(...a),bins=lo===hi?1:18,step=(hi-lo)/bins||1,counts=Array(bins).fill(0);for(const v of a)counts[Math.min(bins-1,Math.floor((v-lo)/step))]++;const max=Math.max(...counts,1),w=320,h=235,left=40,top=15,pw=270,ph=170;let html='<svg viewBox="0 0 '+w+' '+h+'" role="img" aria-label="Гистограмма '+esc(label(metric))+'">';for(let i=0;i<=4;i++){const y=top+ph-i/4*ph;html+='<line class="grid" x1="'+left+'" y1="'+y+'" x2="'+(left+pw)+'" y2="'+y+'"/><text class="axis" x="'+(left-5)+'" y="'+(y+3)+'" text-anchor="end">'+Math.round(i/4*max)+'</text>'}for(let i=0;i<bins;i++){const x=left+i/bins*pw,y=top+ph-counts[i]/max*ph;html+='<rect x="'+x+'" y="'+y+'" width="'+Math.max(1,pw/bins-2)+'" height="'+(top+ph-y)+'" fill="#168b8b"><title>'+esc(number(lo+i*step)+' … '+number(lo+(i+1)*step)+': '+counts[i]+' кварталов')+'</title></rect>'}for(let i=0;i<=4;i++)html+='<text class="axis" x="'+(left+pw*i/4)+'" y="'+(top+ph+18)+'" text-anchor="middle">'+esc(sf.format(lo+(hi-lo)*i/4))+'</text>';html+='<text class="axis" x="'+left+'" y="225">Заполнено: '+a.length+' · нет значения: '+(filtered.length-a.length)+'</text></svg>';element.innerHTML=html}
function renderScatter(){const xk=$('scatterX').value,yk=$('scatterY').value,ids=filtered.filter(i=>finite(rows[i][xk])&&finite(rows[i][yk]));if(!ids.length){$('scatter').innerHTML='<p class="empty">Нет пар числовых значений</p>';return}const xv=ids.map(i=>rows[i][xk]),yv=ids.map(i=>rows[i][yk]);let xmin=Math.min(...xv),xmax=Math.max(...xv),ymin=Math.min(...yv),ymax=Math.max(...yv);if(xmin===xmax){xmin-=.5;xmax+=.5}if(ymin===ymax){ymin-=.5;ymax+=.5}const W=340,H=230,L=43,T=12,PW=282,PH=165;const xp=v=>L+(v-xmin)/(xmax-xmin)*PW,yp=v=>T+PH-(v-ymin)/(ymax-ymin)*PH;let html='<svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="Сопоставление двух показателей">';for(let j=0;j<=4;j++){const x=L+PW*j/4,y=T+PH-PH*j/4;html+='<line class="grid" x1="'+L+'" y1="'+y+'" x2="'+(L+PW)+'" y2="'+y+'"/><text class="axis" x="'+(L-5)+'" y="'+(y+3)+'" text-anchor="end">'+esc(sf.format(ymin+(ymax-ymin)*j/4))+'</text><text class="axis" x="'+x+'" y="'+(T+PH+17)+'" text-anchor="middle">'+esc(sf.format(xmin+(xmax-xmin)*j/4))+'</text>'}for(const i of ids){const r=rows[i];html+='<circle data-point="'+i+'" cx="'+xp(r[xk])+'" cy="'+yp(r[yk])+'" r="3" fill="#087f82" fill-opacity=".42" style="cursor:pointer"><title>'+esc('Квартал '+r.block_id+' · '+xk+': '+valueText(r[xk],xk)+' · '+yk+': '+valueText(r[yk],yk))+'</title></circle>'}html+='<text class="axis" x="'+L+'" y="215">X: '+esc(xk)+' · Y: '+esc(yk)+' · '+ids.length+' кварталов</text></svg>';$('scatter').innerHTML=html}
$('scatter').onclick=e=>{const point=e.target.closest('[data-point]');if(point)selectRow(+point.dataset.point,true)};
function renderInsights(){if(!filtered.length){$('insights').innerHTML='<p>Нет кварталов, соответствующих фильтрам.</p>';return}const lines=[],pop=sum('population'),capacity=sum('capacity'),demand=sum('demand'),within=sum('demand_within'),left=sum('demand_left');if(pop!==null)lines.push('В выборке '+number(filtered.length)+' кварталов; сохранённая оценка населения — '+number(pop)+' человек.');if(capacity!==null&&demand!==null){lines.push('Ёмкость школ — '+number(capacity)+' мест, расчётный спрос — '+number(demand)+'. Это суммарные величины, которые сами по себе не показывают территориальную обеспеченность.');if(demand>0&&within!==null)lines.push('В пределах норматива покрыто '+pct(within/demand)+' суммарного спроса выбранных кварталов'+(left!==null?'; неудовлетворённый спрос — '+number(left)+' мест.':'.'))}const times=values('area_accessibility').sort((a,b)=>a-b);if(times.length)lines.push('Медиана сохранённого средневзвешенного времени — '+number(quantile(times,.5))+' мин; диапазон конечных значений '+number(times[0])+'–'+number(times.at(-1))+' мин.');const unknown=filtered.filter(i=>rows[i].area_accessibility===null||rows[i].area_accessibility===undefined).length;if(unknown)lines.push('У '+number(unknown)+' кварталов нет конечного сохранённого значения доступности. Без специального флага нельзя отличить пропуск от недостижимости.');const mode=distribution('spacematrix_morphotype').find(([k])=>k!=='—');if(mode)lines.push('Самый частый морфотип Spacematrix: «'+mode[0]+'», '+number(mode[1])+' кварталов.');const fsi=values('fsi').sort((a,b)=>a-b);if(fsi.length)lines.push('Медиана FSI — '+number(quantile(fsi,.5))+'. Нулевая застройка включена в распределение; неопределённые значения исключены.');$('insights').innerHTML='<ul>'+lines.map(v=>'<li>'+esc(v)+'</li>').join('')+'</ul><p class="subtle">Это описательная сводка готовых результатов. Фильтрация не пересчитывает маршруты, обеспеченность или морфотипы.</p>'}
function renderCharts(){histogram();bars($('morphChart'),distribution($('morphology').value),$('morphology').value);renderScatter()}
function update(){const land=$('landuse').value,query=$('search').value.trim().toLocaleLowerCase('ru');filtered=rows.map((_,i)=>i).filter(i=>{const r=rows[i],matches=!land||(land==='__null__'?r.land_use===null||r.land_use===undefined:String(r.land_use)===land);return matches&&(!query||fields.some(k=>valueText(r[k],k).toLocaleLowerCase('ru').includes(query)))});if(selected!==null&&!filtered.includes(selected)){paths[selected].classList.remove('selected');selected=null;$('detailTitle').textContent='Выберите квартал';$('details').innerHTML='<p class="subtle">Выбранный квартал исключён фильтром.</p>'}page=0;renderCards();renderMap();renderCharts();renderTable();renderSummary();renderInsights()}
$('metric').onchange=()=>{metric=$('metric').value;renderMap();histogram()};$('landuse').onchange=update;let searchTimer;$('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(update,180)};$('morphology').onchange=()=>bars($('morphChart'),distribution($('morphology').value),$('morphology').value);$('scatterX').onchange=renderScatter;$('scatterY').onchange=renderScatter;
$('reset').onclick=()=>{$('landuse').value='';$('search').value='';sortKey='block_id';sortDir=1;update();$('home').click()};
$('download').onclick=()=>{const cell=v=>{if(v===null||v===undefined)return '""';let s=typeof v==='object'?JSON.stringify(v):String(v);if(typeof v==='string'&&/^[=+@\-]/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"'};const text='\ufeff'+[fields.map(cell).join(';'),...sortedRows().map(i=>fields.map(k=>cell(rows[i][k])).join(';'))].join('\r\n');const url=URL.createObjectURL(new Blob([text],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download='magnitogorsk_filtered.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1500)};
$('sources').textContent='Прочитанные файлы: '+D.sources.join(', ')+' · HTML сформирован: '+D.built_at;
$('metadata').textContent=JSON.stringify(D.metadata,null,2);
if(!D.schools){$('showSchools').disabled=true;$('showSchools').parentNode.title='schools.geojson отсутствовал при сборке'}
function renderSavedTables(){
  const host=$('savedTables');
  for(const entry of D.saved_tables||[]){
    const panel=document.createElement('details');panel.className='panel section';
    const heading=document.createElement('summary');heading.textContent=entry.title+' · '+entry.source+' · '+entry.rows.length+' строк';panel.appendChild(heading);
    const body=document.createElement('div');body.className='table-wrap';panel.appendChild(body);
    panel.addEventListener('toggle',()=>{if(!panel.open||body.dataset.ready)return;body.dataset.ready='1';
      const names={source:'Квартал-источник',target:'Квартал школы',value:'Распределено мест',cluster:'Кластер',number_of_floors:'Сумма этажностей объектов (не L)',count:'Число объектов',is_living:'Сумма признаков is_living'};
      body.innerHTML='<table><thead><tr>'+entry.columns.map(k=>'<th>'+esc(names[k]||D.labels[k]||k)+'</th>').join('')+'</tr></thead><tbody>'+entry.rows.map(row=>'<tr>'+entry.columns.map(k=>'<td>'+esc(row[k]||'—')+'</td>').join('')+'</tr>').join('')+'</tbody></table>';
    });host.appendChild(panel);
  }
}
function renderQuality(){
  const notices=[];
  const zeroed=rows.filter(r=>r.footprint_area===0&&['l','mxi','osr','share_living','share_non_living'].some(k=>r[k]===0)).length;
  if(zeroed)notices.push('У '+zeroed+' кварталов без застройки сохранены нули в неопределённых отношениях. Это признак старого кэша: обновите разделы 9, 10 и 14 с REFRESH_SAVED_DERIVED=True. FSI=0 и GSI=0 сами по себе корректны.');
  const capacityGap=rows.filter(r=>['capacity','capacity_within','capacity_without','capacity_left'].every(k=>finite(r[k]))&&Math.abs(r.capacity-r.capacity_within-r.capacity_without-r.capacity_left)>1e-6).length;
  if(capacityGap)notices.push('У '+capacityGap+' кварталов не сходится баланс школьных мест. В BlocksNet 1.0.0a9 self_supply не отражается в capacity_within. Исправление предусмотрено разделом 9; распределение спроса не меняется.');
  const overlap=rows.filter(r=>['residential','business','recreation','industrial','transport','special','agriculture','share'].some(k=>finite(r[k])&&r[k]>1+1e-6)).length;
  if(overlap)notices.push('У '+overlap+' кварталов сумма пересечений landuse больше 1. Перекрывающиеся полигоны OSM суммируются функцией assign_land_use. Значения не являются непересекающимися долями и не обрезаются до 1.');
  const negativeOSR=rows.filter(r=>finite(r.osr)&&r.osr<0).length;
  if(negativeOSR)notices.push('Отрицательный OSR у '+negativeOSR+' кварталов: сохранённая площадь застройки больше площади квартала. Проверьте пограничные здания и агрегацию по representative_point; показатель не исправляется произвольно.');
  if(!D.metadata.blocksnet)notices.push('В старом run_meta.json не записана версия BlocksNet. Заголовок описывает код, но не доказывает происхождение старого кэша. Раздел 14 обновляет паспорт.');
  notices.push('Историю замены недостижимых пар конечными значениями нельзя проверить по одной матрице. Точное совпадение с эталонным pipeline.ipynb не подтверждено: отдельный файл эталона не предоставлен.');
  $('quality').innerHTML='<ul>'+notices.map(text=>'<li>'+esc(text)+'</li>').join('')+'</ul>';
}
function renderMatrix(){
  const matrix=D.matrix;
  if(!matrix){$('matrixControls').hidden=true;$('matrixTable').hidden=true;$('matrixNote').textContent='Матрица не встроена для уменьшения HTML. Для включения готового accessibility_matrix.csv используйте --include-matrix. Маршруты не пересчитываются.';return}
  $('matrixNote').textContent='Сохранённые значения '+matrix.source+'. Строка — источник, столбец — назначение. Фильтры главной таблицы не меняют матрицу.';
  const text=v=>v==='Infinity'?'Недостижимо':v===null?'Нет значения':number(v)+' мин';
  for(const id of matrix.ids){option($('matrixFrom'),id,'Квартал '+id);option($('matrixTo'),id,'Квартал '+id)}
  function pair(){const row=matrix.rows[$('matrixFrom').value];$('matrixValue').textContent=text(row[matrix.ids.indexOf($('matrixTo').value)])}
  function origin(){const row=matrix.rows[$('matrixFrom').value];$('matrixTable').tBodies[0].innerHTML=matrix.ids.map((id,i)=>'<tr><td>'+esc(id)+'</td><td>'+esc(text(row[i]))+'</td></tr>').join('');pair()}
  $('matrixFrom').onchange=origin;$('matrixTo').onchange=pair;origin();
}
renderSavedTables();renderQuality();renderMatrix();
update();
</script></body></html>"""


if __name__ == "__main__":
    main()

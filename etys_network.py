"""Read ETYS Appendix B into a lossless node/edge graph and schematic map layer.

Only the base circuit/transformer sheets and explicitly existing HVDC rows are
mapped. Coordinates are separate, attributed observations, never inferred from
electrical connectivity. Missing geometry does not remove graph records.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import posixpath
import re
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
OWNERS = dict(zip("abcd", ("SHE", "SPT", "NGET", "OFTO")))
VOLTAGE_SIGNS = {400: "4", 275: "2", 220: "2", 155: "1", 150: "1", 132: "1",
                 66: "6", 34: "3", 33: "3", 25: "7", 20.5: "7", 11: "5"}
COORD_COLUMNS = ["owner", "site_code", "site_name", "voltage_kv", "latitude", "longitude", "source"]

def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None

def normalize(value):
    return re.sub(r"\s+", "", str(value)).lower()

def read_workbook(path):
    """Extract cached scalar values without Excel dependencies or executing formulas."""
    with zipfile.ZipFile(path) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(t.text or "" for t in item.findall(".//s:t", NS))
                       for item in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        relationships = {r.get("Id"): r.get("Target") for r in
                         ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
        result = {}
        for sheet in ET.fromstring(archive.read("xl/workbook.xml")).find("s:sheets", NS):
            name = sheet.get("name")
            if not name.startswith("B-"):
                continue
            target = relationships[sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")]
            target = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            rows = []
            headers = None
            for row in ET.fromstring(archive.read(target)).findall(".//s:sheetData/s:row", NS):
                cells = {}
                for cell in row:
                    value = cell.find("s:v", NS)
                    value = value.text if value is not None else ""
                    if cell.get("t") == "s" and value:
                        value = strings[int(value)]
                    elif cell.get("t") == "inlineStr":
                        value = "".join(t.text or "" for t in cell.findall(".//s:t", NS))
                    cells[re.sub(r"\d", "", cell.get("r"))] = (value or "").strip()
                row_no = int(row.get("r"))
                if row_no == 2:
                    headers = {col: normalize(text) for col, text in cells.items() if text}
                elif row_no > 2 and headers and any(cells.values()):
                    rows.append({**{header: cells.get(col, "") for col, header in headers.items()},
                                 "_sheet": name, "_row": row_no})
            result[name] = rows
        return result

def site_rows(sheets):
    return [{**row, "owner": OWNERS[name[-1]]} for name, rows in sheets.items()
            if name.startswith("B-1-1") and name[-1] in OWNERS for row in rows
            if row.get("sitecode") and row.get("sitename") and number(row.get("voltage(kv)")) is not None]

def site_key(row):
    return (row["owner"], row["sitecode"], row["sitename"].upper(), number(row["voltage(kv)"]))

def valid_location(lat, lon):
    lat, lon = number(lat), number(lon)
    return [lon, lat] if lat is not None and lon is not None and 48 <= lat <= 63 and -15 <= lon <= 5 else None

def seed_coordinates(workbook, destination):
    """Create a separate seed table once. Never overwrite reviewed user edits."""
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite coordinate table: {destination}")
    rows = []
    for row in site_rows(read_workbook(workbook)):
        point = valid_location(row.get("lat"), row.get("lon"))
        if point:
            rows.append(dict(zip(COORD_COLUMNS, [row['owner'], row['sitecode'], row['sitename'],
                        row['voltage(kv)'], point[1], point[0], 'PSALOxford/HunterTracer ETYS 2024; unverified seed'])))
    write_csv(destination, rows, COORD_COLUMNS)
    return len(rows)

def write_csv(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

def load_coordinates(path):
    by_key = defaultdict(list)
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                point = valid_location(row.get("latitude"), row.get("longitude"))
                if point:
                    key = (row['owner'], row['site_code'], row['site_name'].upper(), number(row['voltage_kv']))
                    by_key[key].append((point, row.get('source') or 'coordinate table'))
    return by_key

def build_graph(sheets, coordinate_index, overrides=None):
    overrides = overrides or {}
    sites = site_rows(sheets)
    review = []
    for site in sites:
        candidates = coordinate_index.get(site_key(site), [])
        unique = {tuple(point) for point, _ in candidates}
        site['coordinates'] = list(next(iter(unique))) if len(unique) == 1 else None
        site['coordinate_source'] = '; '.join(sorted({source for _, source in candidates})) if len(unique) == 1 else None
        if not site['coordinates']:
            review.append({'kind':'site', 'owner':site['owner'], 'identifier':site['sitecode'],
                           'name':site['sitename'], 'voltage_kv':site['voltage(kv)'],
                           'reason':'conflicting coordinates' if unique else 'no exact coordinate match'})
    edges, nodes = [], {}
    for sheet, rows in sheets.items():
        if re.fullmatch(r'B-[23]-1[abcd]', sheet):
            kind = 'circuit' if sheet.startswith('B-2') else 'transformer'
            owner = OWNERS[sheet[-1]]
        elif sheet == 'B-5-1':
            kind, owner = 'hvdc', 'GB'
        else:
            continue
        for row in rows:
            if not row.get('node1') or not row.get('node2'):
                continue
            if kind == 'hvdc' and row.get('existing','').lower() != 'yes':
                continue
            endpoints = []
            for name in (row['node1'], row['node2']):
                # Owner-scoped bus identity prevents coincident names being silently merged.
                node_id = f'{owner}:{name}'
                if node_id not in nodes:
                    code = re.match(r'^([A-Z]{4})([1-7])', name)
                    matches = []
                    if code:
                        candidates = [s for s in sites if s['sitecode']==code[1]
                                      and VOLTAGE_SIGNS.get(number(s['voltage(kv)']))==code[2]]
                        own = [s for s in candidates if s['owner']==owner]
                        matches = own or candidates
                    # Cross-owner reuse is allowed only when the site identity and coordinate agree.
                    identities = {(s['sitename'].upper(), number(s['voltage(kv)']),
                                   tuple(s['coordinates'] or [])) for s in matches}
                    match = matches[0] if len(identities)==1 else None
                    point = match['coordinates'] if match else None
                    source = match['coordinate_source'] if match else None
                    override = overrides.get(node_id)
                    if override:
                        point, source = override
                    site_id = f"{match['owner']}:{match['sitecode']}" if match else node_id
                    nodes[node_id] = {'id':node_id, 'node':name, 'owner':owner,
                                      'site_id':site_id, 'site_code':match['sitecode'] if match else None,
                                      'name':match['sitename'] if match else name,
                                      'voltage_kv':number(match['voltage(kv)']) if match else None,
                                      'coordinates':point, 'coordinate_source':source}
                    if not point:
                        review.append({'kind':'node','owner':owner,'identifier':name,
                                       'reason':'ambiguous site lookup' if len(identities)>1 else 'unlocated endpoint'})
                endpoints.append(node_id)
            # Source row identity retains parallel and even identical endpoint pairs.
            edges.append({'id':f'{sheet}:{row["_row"]}', 'kind':kind,'owner':owner,
                          'node_1':endpoints[0], 'node_2':endpoints[1], 'source_sheet':sheet,
                          'source_row':row['_row'], 'attributes':{k:v for k,v in row.items() if not k.startswith('_')}})
    return {'nodes':list(nodes.values()), 'edges':edges}, review

def map_features(graph):
    nodes = {n['id']:n for n in graph['nodes']}
    sites = defaultdict(list)
    for node in nodes.values():
        if node['coordinates']: sites[node['site_id']].append(node)
    features = []
    site_locations = {}
    for site_id, buses in sorted(sites.items()):
        # A representative coordinate is for site display only; every bus retains its own location.
        representative = sorted(buses,key=lambda n:(-(n['voltage_kv'] or 0),n['id']))[0]
        site_locations[site_id] = representative['coordinates']
        features.append({'type':'Feature','geometry':{'type':'Point','coordinates':representative['coordinates']},
                         'properties':{'id':site_id,'kind':'site','name':representative['name'],
                                       'site_code':representative['site_code'],'owner':representative['owner'],
                                       'nodes':[b['id'] for b in buses],
                                       'voltage_kv':sorted({b['voltage_kv'] for b in buses if b['voltage_kv']}, reverse=True),
                                       'coordinate_source':'; '.join(sorted({b['coordinate_source'] for b in buses if b['coordinate_source']}))}})
    for edge in graph['edges']:
        a,b = nodes[edge['node_1']], nodes[edge['node_2']]
        if not a['coordinates'] or not b['coordinates']: continue
        # All drawn connections terminate on their displayed site markers. The
        # full graph above retains the original per-voltage bus coordinates.
        features.append({'type':'Feature', 'geometry':{'type':'LineString','coordinates':[site_locations[a['site_id']],site_locations[b['site_id']]]},
                         'properties':{**edge,'site_1':a['site_id'],'site_2':b['site_id'],
                                       'name':f"{a['name']} — {b['name']}",
                                       'voltage_kv':a['voltage_kv'], 'node_1_label':a['node'], 'node_2_label':b['node']}})
    return features

def build(workbook, coordinates, output, graph_output, review_output, override_path=None, year=2025):
    sheets = read_workbook(workbook)
    required = [f'B-{group}-1{owner}' for group in (1,2,3) for owner in 'abcd'] + ['B-5-1']
    missing = set(required)-set(sheets)
    if missing: raise ValueError(f'Missing ETYS sheets: {sorted(missing)}')
    for sheet in required:
        rows = sheets[sheet]
        columns = {'sitecode', 'sitename', 'voltage(kv)'} if sheet.startswith('B-1-') else {'node1', 'node2'}
        if sheet == 'B-5-1': columns.add('existing')
        if not rows or not columns.issubset(rows[0]):
            raise ValueError(f'Unsupported or empty ETYS sheet {sheet}; expected columns {sorted(columns)}')
    overrides = {}
    if override_path and override_path.exists():
        with override_path.open(encoding='utf-8-sig',newline='') as handle:
            for row in csv.DictReader(handle):
                point = valid_location(row.get('latitude'),row.get('longitude'))
                if not point: raise ValueError(f'Invalid coordinate override: {row.get("node_id")}')
                if row['node_id'] in overrides: raise ValueError(f'Duplicate node override: {row["node_id"]}')
                overrides[row['node_id']] = (point,row.get('source') or 'manual node override')
    graph,review = build_graph(sheets,load_coordinates(coordinates),overrides)
    features = map_features(graph)
    metadata = {'edition':year, 'network_period':f'{year}/{str(year+1)[-2:]}',
                'source_url':'https://www.neso.energy/document/383936/download' if year==2025 else None,
                'source_sha256':hashlib.sha256(workbook.read_bytes()).hexdigest(),
                'coordinates_sha256':hashlib.sha256(coordinates.read_bytes()).hexdigest(),
                'overrides_sha256':hashlib.sha256(override_path.read_bytes()).hexdigest() if override_path and override_path.exists() else None,
                'built_at':datetime.now(timezone.utc).isoformat(),
                'total_edges':len(graph['edges']), 'mapped_edges':sum(f['properties']['kind']!='site' for f in features),
                'mapped_sites':sum(f['properties']['kind']=='site' for f in features),
                'unlocated_nodes':sum(not n['coordinates'] for n in graph['nodes']),
                'notice':'Schematic planning network, not physical routes, live switching states or measured flows. Coordinate seeds are unverified.'}
    for path,payload in [(output,{'type':'FeatureCollection','metadata':metadata,'features':features}),
                         (graph_output,{'metadata':metadata,**graph})]:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False),encoding='utf-8')
    write_csv(review_output,review,['kind','owner','identifier','name','voltage_kv','reason'])
    return metadata

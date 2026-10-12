"""Regression checks for ETYS import identity, missing geometry and parallel edges."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from etys_network import build, build_graph, map_features, seed_coordinates, site_key

def site(code='TEST', name='Test station', owner='NGET', voltage='400'):
    return {'sitecode':code,'sitename':name,'voltage(kv)':voltage,'owner':owner,'_sheet':'B-1-1c','_row':3}

def circuit(a='TEST41', b='NEXT41', row=3):
    return {'node1':a,'node2':b,'_sheet':'B-2-1c','_row':row}

class EtysTests(unittest.TestCase):
    def test_changed_workbook_schema_fails_before_writing(self):
        sheets = {f'B-{group}-1{owner}': [{'renamedcolumn': 'value'}]
                  for group in (1, 2, 3) for owner in 'abcd'}
        sheets['B-5-1'] = [{'node1': 'TEST41', 'node2': 'NEXT41', 'existing': 'Yes'}]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'map.json'
            with patch('etys_network.read_workbook', return_value=sheets):
                with self.assertRaisesRegex(ValueError, 'Unsupported or empty'):
                    build(Path('input.xlsx'), Path('coords.csv'), output, output, output)
            self.assertFalse(output.exists())

    def setUp(self):
        self.a,self.b=site(),site('NEXT','Next station')
        self.coords={site_key(self.a):[([-2,54],'reviewed')],site_key(self.b):[([-1,55],'reviewed')]}
        self.sheets={'B-1-1c':[self.a,self.b], 'B-2-1c':[circuit(),circuit(row=4)]}

    def test_parallel_records_preserved(self):
        graph,_=build_graph(self.sheets,self.coords)
        self.assertEqual(len(graph['edges']),2)
        self.assertEqual(len({e['id'] for e in graph['edges']}),2)
        self.assertEqual(len(map_features(graph)),4)

    def test_unlocated_edges_stay_in_graph(self):
        graph,review=build_graph(self.sheets,{site_key(self.a):self.coords[site_key(self.a)]})
        self.assertEqual(len(graph['edges']),2)
        self.assertFalse(any(f['properties']['kind']=='circuit' for f in map_features(graph)))
        self.assertTrue(any(r['identifier']=='NEXT41' for r in review))

    def test_changed_site_name_does_not_inherit_coordinate(self):
        self.sheets['B-1-1c'][0]={**self.a,'sitename':'Different station'}
        graph,_=build_graph(self.sheets,self.coords)
        self.assertIsNone(next(n for n in graph['nodes'] if n['node']=='TEST41')['coordinates'])

    def test_conflicting_coordinates_not_arbitrarily_selected(self):
        self.coords[site_key(self.a)].append(([-4,58],'conflicting'))
        graph,_=build_graph(self.sheets,self.coords)
        self.assertIsNone(next(n for n in graph['nodes'] if n['node']=='TEST41')['coordinates'])

    def test_same_site_transformer_preserved(self):
        low=site(voltage='132')
        self.sheets['B-1-1c'].append(low)
        self.coords[site_key(low)]=[([-2,54],'reviewed')]
        self.sheets['B-3-1c']=[{**circuit('TEST41','TEST11'),'_sheet':'B-3-1c'}]
        graph,_=build_graph(self.sheets,self.coords)
        self.assertEqual(sum(f['properties']['kind']=='transformer' for f in map_features(graph)),1)

    def test_schematic_edges_terminate_on_grouped_site_marker(self):
        low=site(voltage='132')
        self.sheets['B-1-1c'].append(low)
        self.coords[site_key(low)]=[([-2.01,54.01],'lower voltage compound')]
        self.sheets['B-3-1c']=[{**circuit('TEST41','TEST11'),'_sheet':'B-3-1c'}]
        graph,_=build_graph(self.sheets,self.coords)
        features=map_features(graph)
        marker=next(f for f in features if f['properties']['id']=='NGET:TEST')
        transformer=next(f for f in features if f['properties']['kind']=='transformer')
        self.assertEqual(transformer['geometry']['coordinates'],[marker['geometry']['coordinates']]*2)
        self.assertEqual(next(n for n in graph['nodes'] if n['node']=='TEST11')['coordinates'],[-2.01,54.01])

    def test_planned_hvdc_excluded_and_description_can_be_overridden(self):
        base={'node1':'TEST41','node2':'Central DC Substation','_sheet':'B-5-1','_row':3,'existing':'Yes'}
        self.sheets['B-5-1']=[base,{**base,'_row':4,'existing':'No'}]
        graph,_=build_graph(self.sheets,self.coords,{'GB:Central DC Substation':([-2,56],'manual')})
        self.assertEqual(sum(e['kind']=='hvdc' for e in graph['edges']),1)
        self.assertEqual(sum(f['properties']['kind']=='hvdc' for f in map_features(graph)),1)

    def test_future_sheet_not_imported(self):
        self.sheets['B-2-2c']=[circuit(row=20)]
        graph,_=build_graph(self.sheets,self.coords)
        self.assertEqual(len(graph['edges']),2)

    def test_seed_never_overwrites_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'coordinates.csv'; target.write_text('user edits')
            with self.assertRaises(FileExistsError): seed_coordinates(Path('unused.xlsx'),target)
            self.assertEqual(target.read_text(),'user edits')

if __name__=='__main__': unittest.main()

"""Build the ETYS connectivity graph and map without refreshing existing layers."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from etys_network import build, seed_coordinates

ROOT = Path(__file__).resolve().parents[1]
REGION = ROOT / 'data/regions/uk'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workbook',type=Path,required=True)
    parser.add_argument('--year',type=int,default=2025)
    parser.add_argument('--seed-workbook',type=Path,help='Create the coordinate CSV once from an attributed workbook with lat/lon columns')
    parser.add_argument('--coordinates',type=Path,default=REGION/'reference/editable/etys_coordinates.csv')
    parser.add_argument('--node-overrides',type=Path,default=REGION/'reference/editable/etys_node_coordinates.csv')
    args = parser.parse_args()
    if args.seed_workbook:
        print(f'Seeded {seed_coordinates(args.seed_workbook,args.coordinates)} coordinate records')
    if not args.coordinates.exists(): parser.error('Coordinate CSV missing: use --seed-workbook or supply --coordinates')
    print(json.dumps(build(args.workbook,args.coordinates,REGION/'map/etys_network.geojson',
                           REGION/'reference/generated/etys_graph.json',
                           REGION/'reference/generated/etys_location_review.csv',args.node_overrides,args.year),indent=2))

if __name__=='__main__': main()

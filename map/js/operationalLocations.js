// Reviewed crosswalks only. Unmapped feed entries remain visible in the list.
// Converter locations: existing OSM converters_web.geojson (October 2026).
// Blyth and Bicker Fen: representative points at named OSM substations, not
// the remote converter buildings. These markers never represent cable routes.
export const interconnectorSites = {
  'France(IFA)': {lat:51.10546,lon:0.97468,name:'Sellindge converter'},
  'Eleclink (INTELEC)': {lat:51.09832,lon:1.14524,name:'Folkestone converter'},
  'Belgium (Nemolink)': {lat:51.31014,lon:1.34740,name:'Richborough converter'},
  'Northern Ireland(Moyle)': {lat:55.06939,lon:-4.98152,name:'Auchencrosh converter'},
  'Ireland(East-West)': {lat:53.23656,lon:-3.05080,name:'Shotton converter'},
  'North Sea Link (INTNSL)': {lat:55.1415,lon:-1.531,name:'Blyth connection area'},
  'Denmark (Viking link)': {lat:52.932,lon:-0.221,name:'Bicker Fen connection area'},
};
// NESO explicitly equates SCOTEX/B6 and SSE-SP2/B4:
// https://www.neso.energy/industry-information/balancing-services/local-constraint-market
// Feed uses an underscore in SSE_SP2. Do not infer other codes by similarity.
export const boundaryIds = {SCOTEX:'B6', SSE_SP2:'B4'};

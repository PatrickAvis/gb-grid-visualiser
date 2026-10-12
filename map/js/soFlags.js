// Unknown is deliberately distinct from a published false SO flag.
export const SO_STATES = {
  flagged: {label:'SO-flagged', color:'#d81b60', weight:3, dashArray:''},
  unflagged: {label:'Not SO-flagged', color:'#263238', weight:1, dashArray:''},
  mixed: {label:'Mixed SO flags', color:'#7b1fa2', weight:3, dashArray:'5 3'},
  unknown: {label:'SO flag unknown', color:'#64748b', weight:2, dashArray:'2 3'},
};
export function soStatus(value) {
  return value === true ? 'flagged' : value === false ? 'unflagged' : 'unknown';
}
export function activitySoStatus(props) {
  return Object.hasOwn(SO_STATES, props.so_flag_status) ? props.so_flag_status : 'unknown';
}
export function matchesSoFilter(props, filter) {
  if (filter === 'all') return true;
  if (filter === 'any-flagged') return activitySoStatus(props)==='flagged' || Number(props.so_flagged_actions)>0;
  return activitySoStatus(props) === filter;
}

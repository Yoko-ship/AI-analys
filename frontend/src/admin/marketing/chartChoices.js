// The server validates dates, versions and freshness again before work starts.
export function chartChoices(evidence, selected) {
  return evidence.filter(ev => selected.includes(ev.id) && ev.status === 'verified').flatMap(ev => Object.entries(ev.data)
    .filter(([field, value]) => ev.units[field]?.trim() && Array.isArray(value) && value.length >= 2 && value.length <= 2000
      && value.every(point => point?.date && Number.isFinite(point.value)))
    .map(([field]) => ({ key: `${ev.id}|${field}`, ref: { evidence_id: ev.id, field }, label: `${ev.title} · ${field} · ${ev.units[field]}` })));
}

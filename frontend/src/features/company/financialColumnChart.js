// A compact table cell can contain several independently filed amounts.
// Keep their source identities across periods instead of inventing a total.
const identity = part => JSON.stringify([part.source_form, part.source_code, part.metric_id]);
export function financialChartRows(rows, columns) {
  return rows.flatMap(row => {
    const parts = new Map();
    for (const column of columns) {
      for (const part of row.cells[column.key]?.display_parts || []) parts.set(identity(part), part);
    }
    return [row, ...Array.from(parts, ([key, part]) => ({
      ...row, id: `${row.id}:${key}`,
      label: `${row.label} · ${part.source_code || part.raw_label || part.metric_id}`,
      cells: Object.fromEntries(columns.map(column => [column.key,
        row.cells[column.key]?.display_parts?.find(value => identity(value) === key) || {value:null,quality:'missing'},
      ])),
    }))];
  }).filter(row => columns.some(column => {
    const cell = row.cells[column.key];
    return cell?.value != null && cell.value !== '' && Number.isFinite(Number(cell.value)) && ['valid','warn'].includes(cell.quality);
  }));
}

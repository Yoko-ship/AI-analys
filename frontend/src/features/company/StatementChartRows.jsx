import React from 'react';
import {valueOf} from './financialSourceAmount.js';
import {statementAmountReason} from './statementReportingPeriod.js';

const sameDimension = (first, second) => first == null || second == null || String(first) === String(second);
const lineIdentity = row => JSON.stringify([row.source_form, row.source_code || row.metric_id || row.id]);

function statementCell(row, period, context, duplicate) {
  const cell = row.cells?.[period.key];
  if (!cell) return {quality: 'missing'};
  const matchesSource = source => Object.entries(context ?? {}).every(([key, expected]) =>
    sameDimension(row[key], expected) && sameDimension(source[key], expected)) &&
    ['source_form', 'source_code', 'source_version', 'source_url'].every(key => sameDimension(row[key], source[key]));
  const value = valueOf(cell);
  let reason = null;
  if (duplicate) reason = 'CONFLICTING_SOURCE_VALUES';
  else if (!matchesSource(cell)) reason = 'SOURCE_REPORTING_DIMENSIONS_MISMATCH';
  else if (['valid', 'warn'].includes(cell.quality)) {
    reason = value == null ? 'SOURCE_VALUE_MISSING' : statementAmountReason(cell, row, period, value, matchesSource);
  }
  return reason
    ? {...cell, display_parts: undefined, value: null, quality: 'blocked', reason}
    : {...cell, display_parts: undefined, value};
}

export function StatementChartRows({rows, period, kind, context, matches, renderValue, t}) {
  if (!period) return null;
  const title = t('Все строки отчёта', 'Hisobotning barcha qatorlari', 'All statement rows');
  const unit = value => value === 'UZS_thousand' ? t('тыс. UZS', 'ming UZS', 'thousands UZS') : value;
  const sourceRows = rows.filter(row => row.kind === kind && row.source_form !== 'DERIVED');
  const selectedCounts = new Map();
  for (const row of sourceRows) {
    if (!Object.hasOwn(row.cells ?? {}, period.key)) continue;
    const key = lineIdentity(row);
    selectedCounts.set(key, (selectedCounts.get(key) ?? 0) + 1);
  }
  const statementRows = matches ? sourceRows.filter(matches) : sourceRows;
  return <section className="fc-statement-rows">
    <h3>{title}</h3>
    <table aria-label={title} data-own-export>
      <thead><tr><th scope="col">{t('Показатель', 'Ko‘rsatkich', 'Metric')}</th><th scope="col">{period.label}</th></tr></thead>
      <tbody>{statementRows.map(row => {
        const cell = statementCell(row, period, context, selectedCounts.get(lineIdentity(row)) > 1);
        return <tr key={row.id} data-statement-row={row.id}>
          <th scope="row">{row.label}<small>{row.source_form} {row.source_code}</small></th>
          <td>{renderValue(row, cell, period)}<small>{unit(row.unit)}</small></td>
        </tr>;
      })}
      {statementRows.length === 0 && <tr><td colSpan={2}>{t('Нет подходящих строк', 'Mos qatorlar yo‘q', 'No matching rows')}</td></tr>}
      </tbody>
    </table>
  </section>;
}

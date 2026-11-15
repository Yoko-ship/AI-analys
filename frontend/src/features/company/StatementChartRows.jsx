import React from 'react';

export function StatementChartRows({rows, period, kind, format, t}) {
  if (!period) return null;
  const title = t('Все строки отчёта', 'Hisobotning barcha qatorlari', 'All statement rows');
  const unit = value => value === 'UZS_thousand' ? t('тыс. UZS', 'ming UZS', 'thousands UZS') : value;
  const statementRows = rows.filter(row => row.kind === kind && row.source_form !== 'DERIVED');
  return <section className="fc-statement-rows">
    <h3>{title}</h3>
    <table aria-label={title} data-own-export>
      <thead><tr><th scope="col">{t('Показатель', 'Ko‘rsatkich', 'Metric')}</th><th scope="col">{period.label}</th></tr></thead>
      <tbody>{statementRows.map(row => {
        const cell = row.cells?.[period.key];
        const value = ['valid', 'warn'].includes(cell?.quality) && cell.value != null &&
          String(cell.value).trim() !== '' && Number.isFinite(Number(cell.value)) ? Number(cell.value) : null;
        return <tr key={row.id} data-statement-row={row.id}>
          <th scope="row">{row.label}<small>{row.source_form} {row.source_code}</small></th>
          <td>{format(value)}<small>{unit(row.unit)}</small></td>
        </tr>;
      })}
      {statementRows.length === 0 && <tr><td colSpan={2}>{t('Нет подходящих строк', 'Mos qatorlar yo‘q', 'No matching rows')}</td></tr>}
      </tbody>
    </table>
  </section>;
}

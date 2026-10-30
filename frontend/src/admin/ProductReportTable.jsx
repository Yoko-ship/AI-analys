export function ReportTable({ title, description, columns, rows, empty, children }) {
  return <section className="panel product-report">
    <div className="admin-chart-head"><div><h2>{title}</h2><p>{description}</p></div></div>
    {rows.length ? <div className="admin-scroll" tabIndex={0} role="region" aria-label={title}>
      <table><thead><tr>{columns.map((label, i) => <th key={i} scope="col">{label}</th>)}</tr></thead><tbody>{children}</tbody></table>
    </div> : <p className="admin-muted">{empty}</p>}
  </section>;
}

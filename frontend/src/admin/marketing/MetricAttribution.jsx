export function MetricAttribution({ value }) {
  if (!value) return null;
  return <div className="mkt-metric-coverage"><h5>Проверка атрибуции</h5>
    <p>Клиентов без надёжной атрибуции: {value.unresolved_customers} из {value.customers}.</p>
    <p>Проверяются только клиенты, применимые к этому показателю. Подтверждённые оплаты и расходы сохраняются независимо от источника привлечения.</p>
    {value.reasons.map(row => <p key={row.code}>{row.message} Клиентов: {row.customers}.</p>)}
  </div>;
}

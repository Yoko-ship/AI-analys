

function registryDetailName(detail, lang) {
  if (!detail) return null;
  if (lang === "ru") return detail.name_ru || detail.name_uz_latn || detail.name_uz_cyrl || detail.name;
  if (lang === "uz") return detail.name_uz_latn || detail.name_uz_cyrl || detail.name_ru || detail.name;
  return detail.name || detail.name_uz_latn || detail.name_ru || detail.name_uz_cyrl;
}

function registryPerson(person) {
  if (!person) return null;
  return [person.lastName, person.firstName, person.middleName].filter(Boolean).join(" ");
}

function registryAddress(payload, lang) {
  const address = payload?.companyBillingAddress;
  const company = payload?.company || {};
  if (!address) return company.streetName || null;
  const region = registryDetailName(address.region, lang);
  const district = registryDetailName(address.district, lang);
  const street = address.streetName || company.streetName;
  const house = address.house ? `${lang === "ru" ? "д." : lang === "uz" ? "uy" : "house"} ${address.house}` : null;
  const flat = address.flat ? `${lang === "ru" ? "кв." : lang === "uz" ? "xonadon" : "apt."} ${address.flat}` : null;
  return [address.postcode, region, district, street, house, flat].filter(Boolean).join(", ") || null;
}

function CompanyRegistryCard({ data, loading, error, onRetry, lang }) {
  const tx = lang === "ru" ? {
    heading: "Регистрационные данные", source: "Реестр Налогового комитета",
    fullName: "Полное наименование", shortName: "Краткое наименование", tin: "ИНН",
    status: "Статус", statusUpdated: "Дата изменения статуса", opf: "Организационно-правовая форма",
    oked: "Вид деятельности (ОКЭД)", soogu: "Орган управления (СООГУ)",
    registrator: "Код регистрирующего органа",
    registrationDate: "Дата регистрации", registrationNumber: "Регистрационный номер", reregistrationDate: "Дата перерегистрации",
    liquidationDate: "Дата прекращения деятельности", address: "Юридический адрес", director: "Руководитель", accountant: "Бухгалтер", map: "Расположение компании",
    identity: "Регистрация", classification: "Классификация и налоги", contacts: "Адрес и руководство",
    retry: "Повторить", unavailable: "Регистрационные данные временно недоступны.", loading: "Загрузка регистрационных данных…",
  } : lang === "uz" ? {
    heading: "Ro‘yxatdan o‘tish ma’lumotlari", source: "Soliq qo‘mitasi reyestri",
    fullName: "To‘liq nomi", shortName: "Qisqa nomi", tin: "STIR",
    status: "Holati", statusUpdated: "Holat o‘zgargan sana", opf: "Tashkiliy-huquqiy shakl",
    oked: "Faoliyat turi (IFUT)", soogu: "Boshqaruv organi (SOOGU)",
    registrator: "Ro‘yxatdan o‘tkazuvchi organ kodi",
    registrationDate: "Ro‘yxatdan o‘tgan sana", registrationNumber: "Ro‘yxat raqami", reregistrationDate: "Qayta ro‘yxatdan o‘tgan sana",
    liquidationDate: "Faoliyat tugatilgan sana", address: "Yuridik manzil", director: "Rahbar", accountant: "Buxgalter", map: "Kompaniya joylashuvi",
    identity: "Ro‘yxatdan o‘tish", classification: "Tasnif va soliqlar", contacts: "Manzil va rahbariyat",
    retry: "Qayta urinish", unavailable: "Ro‘yxat ma’lumotlari vaqtincha mavjud emas.", loading: "Ro‘yxat ma’lumotlari yuklanmoqda…",
  } : {
    heading: "Company registry", source: "Tax Committee registry",
    fullName: "Full name", shortName: "Short name", tin: "TIN",
    status: "Status", statusUpdated: "Status updated", opf: "Legal form",
    oked: "Activity (OKED)", soogu: "Governing authority (SOOGU)",
    registrator: "Registration authority code",
    registrationDate: "Registration date", registrationNumber: "Registration number", reregistrationDate: "Re-registration date",
    liquidationDate: "Liquidation date", address: "Legal address", director: "Director", accountant: "Accountant", map: "Company location",
    identity: "Registration", classification: "Classification and taxes", contacts: "Address and management",
    retry: "Retry", unavailable: "Company registry data is temporarily unavailable.", loading: "Loading company registry data…",
  };

  if (loading) return (
    <section className="company-registry" aria-label={tx.heading} aria-busy="true">
      <div className="company-registry-head"><h3 className="co-heading">{tx.heading}</h3><span>{tx.loading}</span></div>
      <div className="company-registry-skeleton" aria-hidden="true">{Array.from({ length: 8 }, (_, i) => <span key={i} />)}</div>
    </section>
  );
  if (error || !data?.registry?.company) return (
    <section className="company-registry" aria-label={tx.heading}>
      <div className="company-registry-head"><h3 className="co-heading">{tx.heading}</h3></div>
      <div className="company-registry-error" role="status"><span>{tx.unavailable}</span><button type="button" onClick={onRetry}>{tx.retry}</button></div>
    </section>
  );

  const payload = data.registry;
  const company = payload.company;
  const hasValue = (value) => value !== null && value !== undefined && value !== "";
  const field = (label, value, wide = false) => (
    <div className={`company-registry-field${wide ? " is-wide" : ""}`} key={label}>
      <span>{label}</span><strong>{value}</strong>
    </div>
  );
  const detail = (object, code) => {
    const name = registryDetailName(object, lang);
    return [code, name].filter((value) => value !== null && value !== undefined && value !== "").join(" · ") || null;
  };
  const address = registryAddress(payload, lang);
  const director = registryPerson(payload.director);
  const accountant = registryPerson(payload.accountant);
  const statusName = registryDetailName(company.statusDetail, lang);
  const statusText = hasValue(statusName) ? statusName : company.status;
  const section = (title, rows, extra = null) => {
    const visibleRows = rows.filter(([, value]) => hasValue(value));
    if (!visibleRows.length && !extra) return null;
    return (
      <div className="company-registry-section">
        <h4>{title}</h4>
        {visibleRows.length > 0 && (
          <div className="company-registry-grid">
            {visibleRows.map(([label, value, wide]) => field(label, value, wide))}
          </div>
        )}
        {extra}
      </div>
    );
  };
  const latitude = Number(data.location?.latitude);
  const longitude = Number(data.location?.longitude);
  const hasLocation = Number.isFinite(latitude) && Number.isFinite(longitude)
    && latitude >= 37 && latitude <= 46 && longitude >= 55 && longitude <= 74;
  const locationMap = hasLocation ? (
    <div className="company-registry-map">
      <iframe
        title={tx.map}
        src={`https://www.google.com/maps?q=${latitude},${longitude}&z=17&output=embed`}
        loading="lazy"
        referrerPolicy="no-referrer-when-downgrade"
        allowFullScreen
      />
    </div>
  ) : null;

  return (
    <section className="company-registry" aria-label={tx.heading} data-testid="company-registry">
      <div className="company-registry-head">
        <div><h3 className="co-heading">{tx.heading}</h3><span>{tx.source}</span></div>
        {hasValue(statusText) && <span className={`company-registry-status ${company.statusDetail?.group === "ACTIVE" ? "is-active" : ""}`}>{statusText}</span>}
      </div>
      {section(tx.identity, [
        [tx.fullName, company.name, true],
        [tx.shortName, company.shortName, true],
        [tx.tin, company.tin || data.tin],
        [tx.status, detail(company.statusDetail, company.status)],
        [tx.statusUpdated, company.statusUpdated],
        [tx.registrationDate, company.registrationDate],
        [tx.registrationNumber, company.registrationNumber],
        [tx.reregistrationDate, company.reregistrationDate],
        [tx.liquidationDate, company.liquidationDate],
        [tx.registrator, company.sooguRegistrator],
      ])}
      {section(tx.classification, [
        [tx.opf, detail(company.opfDetail, company.opf), true],
        [tx.oked, detail(company.okedDetail, company.oked), true],
        [tx.soogu, detail(company.sooguDetail, company.soogu), true],
      ])}
      {section(tx.contacts, [
        [tx.address, address, true],
        [tx.director, director, true],
        [tx.accountant, accountant, true],
      ], locationMap)}
    </section>
  );
}

export { CompanyRegistryCard };

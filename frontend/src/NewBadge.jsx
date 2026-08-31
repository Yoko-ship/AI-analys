import React, { useEffect, useState } from "react";

export default function NewBadge({ until, language = "ru" }) {
  const [now, setNow] = useState(Date.now());
  const end = Date.parse(until || "");
  useEffect(() => {
    setNow(Date.now());
    if (!Number.isFinite(end) || end <= Date.now()) return undefined;
    const id = setTimeout(() => setNow(Date.now()), Math.min(end - Date.now(), 2147483647));
    return () => clearTimeout(id);
  }, [end]);
  if (!Number.isFinite(end) || now >= end) return null;
  return <span className="status-badge" title={new Date(end).toLocaleString()}>
    {language === "en" ? "New" : language === "uz" ? "Yangi" : "Новая"}
  </span>;
}

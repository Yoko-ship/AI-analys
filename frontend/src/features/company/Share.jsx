import React from "react";
import { createPortal } from "react-dom";

function CompanyShareIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M18 8a3 3 0 1 0-2.83-4A3 3 0 0 0 15 5c0 .28.04.55.11.8L8.9 9.3A3 3 0 0 0 6 8a3 3 0 1 0 2.9 3.7l6.2 3.5A3 3 0 0 0 15 16c0 .34.06.67.16.97l-6.23 3.53A3 3 0 1 0 10 22c0-.28-.04-.55-.11-.8l6.2-3.51A3 3 0 0 0 18 18a3 3 0 1 0-2.9-3.7l-6.2-3.5A3 3 0 0 0 9.01 10l6.15-3.48A3 3 0 0 0 18 8Z" fill="currentColor" />
    </svg>
  );
}

function CompanyShareDialog({ ticker, companyName, lang, onClose }) {
  const dialogRef = React.useRef(null);
  const closeRef = React.useRef(null);
  const [copied, setCopied] = React.useState(false);
  const tx = lang === "ru"
    ? { title: "Поделиться", copy: "Копировать ссылку", copied: "Ссылка скопирована", hint: "Отправьте страницу компании коллегам и инвесторам.", close: "Закрыть" }
    : lang === "uz"
      ? { title: "Ulashish", copy: "Havolani nusxalash", copied: "Havola nusxalandi", hint: "Kompaniya sahifasini hamkasblar va investorlar bilan ulashing.", close: "Yopish" }
      : { title: "Share", copy: "Copy link", copied: "Link copied", hint: "Share this company page with colleagues and investors.", close: "Close" };
  const titleId = `company-share-title-${String(ticker || "company").replace(/[^a-zA-Z0-9_-]/g, "-")}`;
  const shareUrl = typeof window === "undefined" ? `/company/${encodeURIComponent(ticker)}` : `${window.location.origin}/company/${encodeURIComponent(ticker)}`;
  const shareTitle = `${companyName} (${ticker}) | UZStock`;
  const shareText = lang === "ru"
    ? `Страница компании ${companyName} (${ticker}) на UZStock`
    : lang === "uz"
      ? `UZStock'dagi ${companyName} (${ticker}) kompaniyasi sahifasi`
      : `${companyName} (${ticker}) company page on UZStock`;
  const encodedUrl = encodeURIComponent(shareUrl);
  const encodedText = encodeURIComponent(shareText);
  const channels = [
    { label: "Telegram", mark: "✈", href: `https://t.me/share/url?url=${encodedUrl}&text=${encodedText}` },
    { label: "Email", mark: "✉", href: `mailto:?subject=${encodeURIComponent(shareTitle)}&body=${encodeURIComponent(`${shareText}\n\n${shareUrl}`)}` },
    { label: "Facebook", mark: "f", href: `https://www.facebook.com/sharer/sharer.php?u=${encodedUrl}` },
    { label: "X", mark: "𝕏", href: `https://x.com/intent/post?text=${encodedText}&url=${encodedUrl}` },
    { label: "LinkedIn", mark: "in", href: `https://www.linkedin.com/sharing/share-offsite/?url=${encodedUrl}` },
  ];

  React.useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    const handleKey = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = [...dialogRef.current.querySelectorAll('button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])')].filter((element) => element.getClientRects().length > 0);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKey);
    };
  }, [onClose]);

  const copyLink = async () => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(shareUrl);
      } else {
        const input = document.createElement("textarea");
        input.value = shareUrl;
        input.setAttribute("readonly", "");
        input.style.position = "fixed";
        input.style.opacity = "0";
        document.body.appendChild(input);
        input.select();
        document.execCommand("copy");
        input.remove();
      }
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return createPortal((
    <div className="company-share-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <article ref={dialogRef} className="company-share-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <button ref={closeRef} className="company-share-close" type="button" onClick={onClose} aria-label={tx.close}>×</button>
        <h2 id={titleId}>{tx.title}</h2>
        <p className="company-share-hint">{tx.hint}</p>
        <div className="company-share-preview">
          <span>{ticker}</span>
          <strong>{companyName}</strong>
          <small>uzstock.uz</small>
        </div>
        <button className="company-share-copy" type="button" onClick={copyLink}>
          <CompanyShareIcon />
          <span>{copied ? tx.copied : tx.copy}</span>
        </button>
        <div className="company-share-channels" aria-label={tx.title}>
          {channels.map((channel) => (
            <a key={channel.label} href={channel.href} target={channel.href.startsWith("mailto:") ? undefined : "_blank"} rel={channel.href.startsWith("mailto:") ? undefined : "noreferrer"}>
              <span className="company-share-channel-mark" aria-hidden="true">{channel.mark}</span>
              <span>{channel.label}</span>
            </a>
          ))}
        </div>
      </article>
    </div>
  ), document.body);
}

export { CompanyShareDialog, CompanyShareIcon };

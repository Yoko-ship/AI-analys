import React from "react";

function ShareIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M18 8a3 3 0 1 0-2.83-4A3 3 0 0 0 15 5c0 .28.04.55.11.8L8.9 9.3A3 3 0 0 0 6 8a3 3 0 1 0 2.9 3.7l6.2 3.5A3 3 0 0 0 15 16c0 .34.06.67.16.97l-6.23 3.53A3 3 0 1 0 10 22c0-.28-.04-.55-.11-.8l6.2-3.51A3 3 0 0 0 18 18a3 3 0 1 0-2.9-3.7l-6.2-3.5A3 3 0 0 0 9.01 10l6.15-3.48A3 3 0 0 0 18 8Z" fill="currentColor" />
    </svg>
  );
}

const SHARE_TX = {
  ru: { copy: "Копировать ссылку", copied: "Ссылка скопирована", more: "Другие приложения", channels: "Поделиться через" },
  uz: { copy: "Havolani nusxalash", copied: "Havola nusxalandi", more: "Boshqa ilovalar", channels: "Ulashish" },
  en: { copy: "Copy link", copied: "Link copied", more: "More apps", channels: "Share via" },
};

// Whether the browser hands a link to the system share sheet — on phones
// that sheet is the only way into Instagram, which has no web share URL.
const canShareNatively = () => typeof navigator !== "undefined" && typeof navigator.share === "function";

async function shareNatively({ url, title, text }) {
  try {
    await navigator.share({ url, title, text });
    return true;
  } catch (error) {
    // The reader closing the sheet is an answer, not a failure.
    return error?.name === "AbortError";
  }
}

async function copyText(value) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const input = document.createElement("textarea");
  input.value = value;
  input.setAttribute("readonly", "");
  input.style.position = "fixed";
  input.style.opacity = "0";
  document.body.appendChild(input);
  input.select();
  document.execCommand("copy");
  input.remove();
}

function shareChannels({ url, title, text }) {
  const encodedUrl = encodeURIComponent(url);
  const encodedText = encodeURIComponent(text);
  return [
    { label: "Telegram", mark: "✈", href: `https://t.me/share/url?url=${encodedUrl}&text=${encodedText}` },
    { label: "WhatsApp", mark: "☏", href: `https://wa.me/?text=${encodeURIComponent(`${text}\n${url}`)}` },
    { label: "Facebook", mark: "f", href: `https://www.facebook.com/sharer/sharer.php?u=${encodedUrl}` },
    { label: "X", mark: "𝕏", href: `https://x.com/intent/post?text=${encodedText}&url=${encodedUrl}` },
    { label: "LinkedIn", mark: "in", href: `https://www.linkedin.com/sharing/share-offsite/?url=${encodedUrl}` },
    { label: "Email", mark: "✉", href: `mailto:?subject=${encodeURIComponent(title)}&body=${encodeURIComponent(`${text}\n\n${url}`)}` },
  ];
}

// The links a page can be passed on through: copy, the messengers and
// networks by their web share URLs, and the system sheet where there is one.
function SharePanel({ url, title, text, lang, id }) {
  const tx = SHARE_TX[lang] || SHARE_TX.ru;
  const [copied, setCopied] = React.useState(false);
  const copyLink = async () => {
    try {
      await copyText(url);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  return (
    <div className="share-panel" id={id}>
      <div className="share-panel-actions">
        <button className="share-panel-copy" type="button" onClick={copyLink} aria-live="polite">
          <ShareIcon />
          <span>{copied ? tx.copied : tx.copy}</span>
        </button>
        {canShareNatively() && (
          <button className="share-panel-copy" type="button" onClick={() => shareNatively({ url, title, text })}>
            <span aria-hidden="true">⋯</span>
            <span>{tx.more}</span>
          </button>
        )}
      </div>
      <div className="share-panel-channels" role="group" aria-label={tx.channels}>
        {shareChannels({ url, title, text }).map((channel) => (
          <a key={channel.label} href={channel.href} target={channel.href.startsWith("mailto:") ? undefined : "_blank"} rel={channel.href.startsWith("mailto:") ? undefined : "noopener noreferrer"}>
            <span className="share-panel-mark" aria-hidden="true">{channel.mark}</span>
            <span>{channel.label}</span>
          </a>
        ))}
      </div>
    </div>
  );
}

export { SharePanel, ShareIcon, canShareNatively, shareNatively };

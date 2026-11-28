"""Owner-selected reader routes and fresh proof of the exact profile destination."""
import re
import unicodedata

COPY = {"ru": "Подробнее — по ссылке в профиле.", "uz": "Batafsil — profildagi havola orqali.",
        "en": "Read more via the link in our profile."}
FREEFORM_REASON = "Instagram link instructions must use the selected route, not freeform copy"
PROFILE_REASON = "Instagram profile link must match this material's exact destination before publication"


def caption(item):
    return COPY[item["language"]] if item.get("instagram_link") == "profile" else ""


def check(account, item):
    instagram = account and account["platform"] == "instagram"
    if item.get("instagram_link", "none") != "none" and not instagram:
        return ["The Instagram profile route requires an Instagram account"]
    if not instagram:
        return []
    text = " ".join(unicodedata.normalize("NFKC", str(item[key])).casefold() for key in ("title", "body"))
    text = " ".join("".join(letter for letter in text if unicodedata.category(letter) != "Cf").split())
    # A supported route owns the CTA. Freeform copy may discuss company profiles,
    # but cannot promise unverified profile, caption or Story links/stickers.
    link = r"(?:ссыл\w{0,30}|havola\w{0,30}|links?)"
    place = r"(?:профил\w{0,30}|био\b|profil\w{0,30}|profiles?|bio\b|stor(?:y|ies)|сторис|истори\w{0,30}|stiker\w{0,30}|стикер\w{0,30}|stickers?|описани\w{0,30}|description|izoh\w{0,30})"
    near = r"[^.!?]{0,80}"
    action = r"(?:откро\w{0,30}|откры\w{0,30}|перей\w{0,30}|переход\w{0,30}|заглян\w{0,30}|смотр\w{0,30}|open|visit|check|go|kiring|bosing)"
    if (re.search(link + near + place + "|" + place + near + link, text)
            or re.search(action + near + r"(?:профил\w{0,30}|profil\w{0,30}|profiles?|bio\b)", text)
            or re.search(r"\b(?:swipe\s+up|yuqoriga\s+suring|свайп\w{0,30}\s+вверх)\b", text)):
        return [FREEFORM_REASON]
    return []


def verify(account, item, request, now):
    if item.get("instagram_link") != "profile":
        return None
    from . import checks, publication_links
    from .delivery import StoppedBeforeSend
    value = request("GET", account["external_id"], data={"fields": "id,website"})
    destination = publication_links.destination(item)
    # Do not follow a provider URL or discard its query/fragment: these identify
    # the exact report version, language, financial scope and publication.
    if (value.get("id") != account["external_id"] or not destination or not checks.public_url(destination)
            or value.get("website") != destination):
        raise StoppedBeforeSend(PROFILE_REASON, invalidated=True)
    return {"url": destination, "account_external_id": account["external_id"], "checked_at": now().isoformat()}

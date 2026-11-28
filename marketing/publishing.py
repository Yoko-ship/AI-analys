"""The outgoing copy, including destination and original links, before transport."""
import re
from . import instagram_links, publication_links
from .catalog import FORMATS


def text(item, evidence):
    parts = [item["body"]]
    if item["title"] not in item["body"]:
        parts.insert(0, item["title"])
    destination = publication_links.destination(item)
    if item['destination_url'] and destination != item['destination_url']:
        # Replace a complete URL token, never another URL sharing its prefix.
        pattern = re.escape(item['destination_url']) + r'(?=$|[\s<>"\u201c\u201d]|[.,;:!?)](?=$|[\s.,;:!?]))'
        parts = [re.sub(pattern, lambda _: destination, part) for part in parts]
    if destination and destination not in "\n\n".join(parts):
        parts.append(destination)
    originals = list(dict.fromkeys(ev["url"] for ev in evidence.values() if ev and ev.get("url")))
    originals = [url for url in originals if url not in "\n\n".join(parts)]
    if originals:
        label = {"ru": "Первоисточники", "uz": "Birlamchi manbalar", "en": "Original sources"}[item["language"]]
        parts.append(label + ":\n" + "\n".join(originals))
    return "\n\n".join(parts)


def media_only(account, item):
    return bool(account and account["platform"] == "instagram" and item["format"] == "story")


def payload_text(account, item, evidence):
    if media_only(account, item):
        return ""
    if (account and account['platform'] == 'telegram' and account.get('automatic_news')
            and item['rubric'] == 'news' and publication_links.valid_destination(item['destination_url'])):
        return telegram_news_text(item, evidence)
    copy = text(item, evidence)
    return copy + "\n\n" + instagram_links.caption(item) if account and account["platform"] == "instagram" and instagram_links.caption(item) else copy


def telegram_news_text(item, evidence):
    originals = {ev['url'] for ev in evidence.values() if ev and ev.get('url')}
    publishers = {ev['publisher'] for ev in evidence.values() if ev and ev.get('publisher')}
    credit = r'^\s*(?:источник(?:и)?|первоисточники|(?:original )?sources?|(?:birlamchi )?manba(?:lar)?)\s*:'
    lines = [line for line in item['body'].splitlines()
             if not re.match(credit, line, re.I) and line.strip() not in originals | publishers]
    body = '\n'.join(lines).strip()
    for publisher in publishers:
        name = re.escape(publisher)
        body = re.sub(r'(?im)^(?:По сообщению|According to)\s+' + name + r'\s*,\s*', '', body)
        body = re.sub(r'(?im)^' + name + r'\s+xabariga ko[‘’\x27]ra\s*,\s*', '', body)
    label = {'ru': 'Источник', 'uz': 'Manba', 'en': 'Source'}[item['language']]
    return text({**item, 'body': body + '\n\n' + label + ': UZStock'}, {})


def check(account, item, evidence):
    if reasons := instagram_links.check(account, item):
        return reasons
    if account and account["platform"] == "instagram":
        if item["format"] not in FORMATS['instagram']:
            return ["Instagram publishing requires finished images, photo carousels, Reels or Stories"]
        if item["format"] == "carousel" and item["assets"] and not 2 <= len(item["assets"]) <= 10:
            return ["Instagram carousels require between two and ten rendered images"]
        copy = payload_text(account, item, evidence)
        if len(copy) > 2200 or len(re.findall(r"(?<!\w)#[\w]+", copy)) > 30 or len(re.findall(r"(?<!\w)@[\w.]+", copy)) > 20:
            return ["Instagram caption exceeds its text, hashtag or mention limits"]
        return []
    if account and account["platform"] == "facebook":
        if item["format"] not in FORMATS['facebook']:
            return ["Facebook publishing does not support this format yet"]
        if item["format"] == "carousel" and item["assets"] and not 2 <= len(item["assets"]) <= 10:
            return ["Facebook photo posts require between two and ten rendered images"]
        copy = text(item, evidence)
        if re.search(r"@\[[^\]]*\]", copy):
            return ["Facebook mention syntax requires a plain-text revision"]
        if len(copy.encode("utf-16-le")) // 2 > 63206:
            return ["Facebook outgoing text including original links exceeds 63206 characters"]
        return []
    if account and account["platform"] == "linkedin":
        if item["format"] not in FORMATS['linkedin']:
            return ["LinkedIn publishing does not support this format"]
        if item["format"] == "carousel" and item["assets"] and not 2 <= len(item["assets"]) <= 20:
            return ["LinkedIn multi-image posts require between two and twenty images"]
        if len(text(item, evidence).encode("utf-16-le")) // 2 > 3000:
            return ["LinkedIn outgoing text including original links exceeds 3000 characters"]
        return []
    if not account or account["platform"] != "telegram":
        return []
    if item["format"] not in FORMATS['telegram']:
        return ["Telegram channel publishing does not support this format"]
    if item["format"] == "carousel" and item["assets"] and not 2 <= len(item["assets"]) <= 10:
        return ["Telegram albums require between two and ten rendered files"]
    limit = 4096 if item["format"] == "post" else 1024
    # UTF-16 units conservatively account for Telegram's entity offsets and emoji.
    if len(payload_text(account, item, evidence).encode("utf-16-le")) // 2 > limit:
        return [f"Telegram outgoing text including original links exceeds {limit} characters"]
    return []


def evidence_for(c, item):
    from . import sources, store as s
    pinned = item["status"] in {"published", "submitted", "sending", "unknown"}
    versions = (item.get("check") or {}).get("evidence_versions", {})
    return {key: (s.revision(c, "evidence", key, versions[key]) if pinned and key in versions else sources.current_evidence(c, key))
            for key in item["evidence_ids"]}


def preview(c, item, *, evidence=None):
    from . import store as s
    evidence = evidence_for(c, item) if evidence is None else evidence
    account = s.get(c, "account", item["account_id"], required=False)
    if item['status'] in {'published', 'submitted', 'sending', 'unknown'}:
        job = s.get(c, 'delivery', item['id'], required=False)
        if job and job.get('platform'):
            account = {**(account or {}), 'platform': job['platform']}
    return {"text": payload_text(account, item, evidence), "media_only": media_only(account, item), "candidate_version": item["version"], "platform": account["platform"] if account else None,
            "instagram_link": item.get("instagram_link", "none"), "link_destination": publication_links.destination(item) if item.get("instagram_link") == "profile" else None,
            "tracked_destination": (item.get('tracking') or {}).get('destination'), "tracking_dataset": (item.get('tracking') or {}).get('dataset'),
            "reasons": check(account, item, evidence)}

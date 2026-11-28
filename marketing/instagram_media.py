"""Durable unpublished media containers; no publication operation lives here."""
import io

from PIL import Image

from . import media, meta_identity, public_media, store as s
from .delivery import PermanentRejection, PreparationPending
from .upload_journal import UploadJournal


def files(item):
    refs = item["assets"]
    if (item["format"] not in {"image", "carousel", "video", "story"} or len({ref["id"] for ref in refs}) != len(refs)
            or not (2 <= len(refs) <= 10 if item["format"] == "carousel" else len(refs) == 1)):
        raise PermanentRejection("Instagram requires a finished image or a carousel of two to ten images")
    result, sizes = [], set()
    with s.connection() as c:
        assets = [s.get(c, "asset", ref["id"]) for ref in refs]
    if item["format"] == "video":
        from .instagram_video import validate
        validate(assets[0])
        return assets
    for asset in assets:
        try:
            raw = media.read_asset(asset)
            with Image.open(io.BytesIO(raw)) as image:
                aspect = image.width * 16 == image.height * 9 if item["format"] == "story" else .8 <= image.width / image.height <= 1.91
                if (image.format != "JPEG" or image.mode != "RGB" or asset["mime"] != "image/jpeg" or len(raw) > 8_000_000
                        or not 320 <= image.width <= 1440 or not aspect
                        or not isinstance(asset.get("alt_text"), str) or not 1 <= len(asset["alt_text"]) <= 1000):
                    raise ValueError("Invalid JPEG")
                sizes.add(image.size)
                image.verify()
        except Exception:
            raise PermanentRejection("Instagram needs verified JPEG files within its image limits") from None
        result.append(asset)
    if len(sizes) != 1:
        raise PermanentRejection("Instagram carousel images must share the reviewed dimensions")
    return result


def prepare(account, item, assets, grant, release_id, claim_token, copy, at, check, request):
    journal = UploadJournal(account, item, grant, assets[0], release_id, claim_token, at(), provider="instagram")
    state = journal.load() or {"remote_id": "", "phase": "registered", "parts": [asset["id"] for asset in assets],
                               "completed": [], "containers": [], "root": None, "attempts": 0, "generations": 1, "retired": []}

    def save():
        check()
        journal.save(state)

    def create(data):
        if state["attempts"] >= 3 * (len(assets) + 1):
            raise PermanentRejection("Instagram container creation requires review")
        state["attempts"] += 1
        save()
        value = request("POST", account["external_id"] + "/media", data=data)
        try:
            identifier = meta_identity.identifier(value.get("id"))
        except Exception:
            raise PermanentRejection("Instagram did not return a valid media container") from None
        if identifier in state["retired"] or identifier in [row["id"] for row in state["containers"]]:
            raise PermanentRejection("Instagram returned a duplicate media container")
        return identifier

    def ready(identifier):
        value = request("GET", identifier, data={"fields": "id,status_code"})
        if value.get("id") != identifier:
            raise PermanentRejection("Instagram returned a different media container")
        status = value.get("status_code")
        if status == "EXPIRED":
            if state["generations"] >= 3:
                raise PermanentRejection("Instagram media repeatedly expired; review the release")
            state["retired"].extend([row["id"] for row in state["containers"]] + ([state["root"]] if state["root"] else []))
            state.update(containers=[], root=None, remote_id="", completed=[], phase="expired", generations=state["generations"] + 1, polls=0)
            save()
            raise PreparationPending("Instagram media expired before publication; preparing a new container", 60)
        if status == "IN_PROGRESS":
            state.update(phase="processing", polls=state.get("polls", 0) + 1)
            save()
            if state["polls"] > 5:
                raise PermanentRejection("Instagram media processing did not finish; review the release")
            raise PreparationPending("Instagram is processing the approved media", 60)
        if status != "FINISHED":
            state.update(phase="failed")
            save()
            raise PermanentRejection("Instagram container is not eligible for publication")

    if not state["root"]:
        for index, asset in enumerate(assets):
            if len(state["containers"]) <= index:
                check()
                url = public_media.issue(account, item, asset, release_id, claim_token, grant, at())
                data = ({"image_url": url, "media_type": "STORIES"} if item["format"] == "story" else
                        {"video_url": url, "media_type": "REELS", "share_to_feed": "false"} if item["format"] == "video" else
                        {"image_url": url, "alt_text": asset["alt_text"]})
                data.update({"is_carousel_item": "true"} if item["format"] == "carousel" else
                            {"is_ai_generated": "true"} if item["format"] == "story" else {"caption": copy, "is_ai_generated": "true"})
                identifier = create(data)
                state["containers"].append({"id": identifier, "ready": False})
                state.update(remote_id=identifier, phase="uploaded")
                save()
            row = state["containers"][index]
            if not row["ready"]:
                ready(row["id"])
                row["ready"] = True
                state["completed"].append(index)
                state["polls"] = 0
                save()
        root = (create({"media_type": "CAROUSEL", "children": ",".join(row["id"] for row in state["containers"]),
                        "caption": copy, "is_ai_generated": "true"}) if item["format"] == "carousel" else state["containers"][0]["id"])
        state.update(root=root, remote_id=root)
        save()
    ready(state["root"])
    state.update(phase="ready", polls=0)
    save()
    return state["root"]

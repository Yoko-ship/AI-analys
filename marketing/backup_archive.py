"""Validate the complete archive before restoring records or media."""
import hashlib
import json
import re
from pathlib import PurePosixPath

from .errors import MarketingError

FORMAT = 1
MAX_TOTAL = 1_000_000_000
MAX_MANIFEST = 32_000_000


def invalid():
    return MarketingError("INVALID_BACKUP", "Invalid or incomplete marketing archive.", 422)


def media_name(name):
    if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", name)
            or name.endswith(".") or PurePosixPath(name).name != name
            or re.fullmatch(r"CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9]", name.split(".")[0], re.IGNORECASE)):
        raise invalid()
    return "media/" + name


def files_for(revisions):
    files = {}
    for row in revisions:
        if row["kind"] != "asset":
            continue
        asset = json.loads(row["payload"])
        if asset.get("status") != "ready":
            continue
        name = media_name(asset.get("file_name"))
        digest = asset.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise invalid()
        if name in files and files[name]["sha256"] != digest:
            raise invalid()
        files[name] = asset
    if len({name.casefold() for name in files}) != len(files):
        raise invalid()
    return files


def validate_records(manifest):
    if (manifest.get("format") != FORMAT or manifest.get("schema") != "marketing-v1"
            or not isinstance(manifest.get("environment"), str) or not isinstance(manifest.get("created_at"), str)):
        raise invalid()
    records, histories = {}, {}
    for row in manifest["records"]:
        value = json.loads(row["payload"])
        key = (row["kind"], row["id"])
        if (key in records or not all(isinstance(part, str) and part for part in key)
                or type(row["version"]) is not int or row["version"] < 1
                or value.get("id") != row["id"] or value.get("version") != row["version"]
                or value.get("status", "") != row["status"] or value.get("updated_at") != row["updated_at"]):
            raise invalid()
        records[key] = row
    for row in manifest["revisions"]:
        key = (row["kind"], row["id"])
        value = json.loads(row["payload"])
        actor = json.loads(row["actor"])
        history = histories.setdefault(key, {})
        version = row["version"]
        if (key not in records or type(version) is not int or version < 1 or version in history
                or value.get("id") != row["id"] or value.get("version") != version
                or value.get("updated_at") != row["created_at"] or not isinstance(actor, dict)
                or not isinstance(row["action"], str)):
            raise invalid()
        history[version] = row["payload"]
    for key, record in records.items():
        history = histories.get(key, {})
        count = record["version"]
        if len(history) != count or set(history) != set(range(1, count + 1)) or history[count] != record["payload"]:
            raise invalid()
    return files_for(manifest["revisions"])


def read(archive):
    try:
        entries = archive.infolist()
        if len(entries) > 100000 or sum(info.file_size for info in entries) > MAX_TOTAL:
            raise invalid()
        names = {info.filename for info in entries}
        if len(names) != len(entries) or archive.getinfo("manifest.json").file_size > MAX_MANIFEST:
            raise invalid()
        manifest = json.loads(archive.read("manifest.json"))
        files = validate_records(manifest)
        if names != {"manifest.json", *files}:
            raise invalid()
        for name, asset in files.items():
            if not 0 < archive.getinfo(name).file_size <= 30_000_000:
                raise invalid()
            hasher = hashlib.sha256()
            with archive.open(name) as stream:
                for chunk in iter(lambda: stream.read(1_048_576), b""):
                    hasher.update(chunk)
            if hasher.hexdigest() != asset["sha256"]:
                raise invalid()
        return manifest, files
    except MarketingError:
        raise
    except Exception:
        raise invalid() from None


def summary(manifest, files):
    return {"source_environment": manifest["environment"], "created_at": manifest["created_at"],
            "records": len(manifest["records"]), "revisions": len(manifest["revisions"]), "media_files": len(files)}

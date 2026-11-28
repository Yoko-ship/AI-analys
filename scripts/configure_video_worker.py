"""Save the scoped video-worker credential received on stdin in a private env."""
import os
from pathlib import Path
import re
import sys
import tempfile


def configure(path, token):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43,100}", token):
        raise ValueError("Invalid video worker credential")
    lines = [line for line in path.read_text(encoding="utf-8").splitlines()
             if line.split("=", 1)[0].strip() != "MARKETING_VIDEO_WORKER_TOKEN"]
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".video-worker-")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write("\n".join([*lines, f"MARKETING_VIDEO_WORKER_TOKEN={token}"]) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    configure(Path(sys.argv[1]), sys.stdin.read())
    print("Scoped video worker credential saved privately.")

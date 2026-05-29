"""Scope the entire 'NEWSPAPER THEME' CSS block to body[data-theme="light"].

In dark mode the unscoped newspaper rules (with !important) override the
dark surface/text styles and make the analysis report unreadable.

Strategy: prefix every selector in the newspaper section with
`body[data-theme="light"]` so the newspaper look stays put for light mode
but the dark-theme tokens win in dark mode.

The :root vars block is left untouched (it just defines --np-* tokens).
@media wrappers and nested keyframes are passed through.
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

CSS = Path("frontend/src/styles.css")
SCOPE = 'body[data-theme="light"]'

src = CSS.read_text(encoding="utf-8").splitlines(keepends=True)

# Find the newspaper section marker.
start = None
for i, line in enumerate(src):
    if "NEWSPAPER THEME" in line:
        start = i
        break
if start is None:
    raise SystemExit("NEWSPAPER THEME marker not found")

end = len(src)

# Walk forward, finding selectors at brace depth 0 (top-level rules in this
# block), and prefix each comma-separated selector with the scope.
out: list[str] = src[:start]
depth = 0
buf: list[str] = []
in_root = False
in_at_rule = False
at_depth = 0

i = start
modified = 0
preserved = 0

def scope_selector_list(sel_text: str) -> str:
    """Prefix each comma-separated selector with body[data-theme='light']."""
    parts = [p.strip() for p in sel_text.split(",")]
    out_parts = []
    for p in parts:
        if not p:
            out_parts.append(p)
            continue
        # Don't double-scope.
        if p.startswith(SCOPE):
            out_parts.append(p)
            continue
        # Don't touch :root, keyframes, media query content selectors are
        # handled at the @ rule level.
        if p == ":root" or p.startswith("@"):
            out_parts.append(p)
            continue
        # If the selector already contains body[data-theme=, it's an explicit
        # override — keep as is.
        if 'body[data-theme=' in p:
            out_parts.append(p)
            continue
        out_parts.append(f"{SCOPE} {p}")
    return ", ".join(out_parts)


# Simpler tokenizer: scan char by char tracking depth, collect "selector" text
# preceding `{`, transform if at depth 0, and emit.
text = "".join(src[start:end])
result_chars: list[str] = []
i = 0
n = len(text)
buf_chars: list[str] = []
depth = 0
in_comment = False

while i < n:
    ch = text[i]
    nxt = text[i + 1] if i + 1 < n else ""

    if in_comment:
        result_chars.append(ch)
        if ch == "*" and nxt == "/":
            result_chars.append(nxt)
            i += 2
            in_comment = False
            continue
        i += 1
        continue

    if ch == "/" and nxt == "*":
        # Flush buf first.
        result_chars.append("".join(buf_chars))
        buf_chars = []
        result_chars.append(ch)
        result_chars.append(nxt)
        in_comment = True
        i += 2
        continue

    if ch == "{":
        if depth == 0:
            sel = "".join(buf_chars).strip()
            # Preserve leading whitespace/newlines.
            lead_ws_len = len("".join(buf_chars)) - len("".join(buf_chars).lstrip())
            lead = "".join(buf_chars)[:lead_ws_len]
            if sel.startswith("@"):
                # @media / @supports etc. — leave selector as-is; we'll re-enter
                # at deeper level to scope inner selectors.
                result_chars.append(lead + sel + " ")
                preserved_local = True
            elif sel == ":root":
                result_chars.append(lead + sel + " ")
            else:
                scoped = scope_selector_list(sel)
                if scoped != sel:
                    modified += 1
                else:
                    preserved += 1
                result_chars.append(lead + scoped + " ")
            buf_chars = []
            result_chars.append(ch)
            depth += 1
            i += 1
            continue
        else:
            buf_chars.append(ch)
            depth += 1
            i += 1
            continue

    if ch == "}":
        if depth == 1:
            # Closing top-level rule. Emit any buffered content then '}'.
            result_chars.append("".join(buf_chars))
            buf_chars = []
            result_chars.append(ch)
            depth = 0
            i += 1
            continue
        elif depth > 1:
            # Inner block (e.g., inside @media). We need to also scope nested
            # rules inside @media. Track second-level selectors.
            # For simplicity: collect inner block until matching brace and
            # post-process.
            buf_chars.append(ch)
            depth -= 1
            i += 1
            continue
        else:
            buf_chars.append(ch)
            i += 1
            continue

    buf_chars.append(ch)
    i += 1

# Flush any trailing buffer.
result_chars.append("".join(buf_chars))

newspaper_text = "".join(result_chars)

# Now handle @media / @supports rules within the newspaper section: scope
# their inner top-level selectors too.
# Find each `@media ... { ... }` block and rewrite inner selectors.
def rescope_inside_at_rule(at_block: str) -> str:
    # at_block includes "@media ... { ... }"
    m = re.match(r"^(@[\w-]+[^{]*\{)(.*)(\})$", at_block, re.DOTALL)
    if not m:
        return at_block
    head, inner, tail = m.group(1), m.group(2), m.group(3)
    # Inner is a sequence of `selector { ... }` rules at depth 0 relative to
    # the @media block. Scope each.
    rewritten = re.sub(
        r"([^{}]+?)(\{[^{}]*\})",
        lambda mm: scope_selector_list(mm.group(1).strip()).rjust(0) + " " + mm.group(2)
        if not mm.group(1).strip().startswith("@") and mm.group(1).strip() != ":root"
        else mm.group(1) + mm.group(2),
        inner,
        flags=re.DOTALL,
    )
    # Restore leading whitespace before each selector.
    return head + rewritten + tail

newspaper_text = re.sub(
    r"@[\w-]+[^{]*\{(?:[^{}]|\{[^{}]*\})*\}",
    lambda m: rescope_inside_at_rule(m.group(0)),
    newspaper_text,
    flags=re.DOTALL,
)

CSS.write_text("".join(out) + newspaper_text, encoding="utf-8")
print(f"scoped {modified} selectors, left {preserved} untouched")

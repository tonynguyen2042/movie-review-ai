"""Safe JSON embedding for inline <script> blocks.

``json.dumps`` does not escape ``<`` or ``/``, so a value containing
``</script>`` would terminate the inline script element early and let
model-produced text (character names, review prose, event descriptions)
execute as JavaScript. Escaping ``<``, ``>``, ``&`` and U+2028/U+2029
makes the payload inert while remaining valid JSON.
"""

from __future__ import annotations

import json
from typing import Any

# Line/paragraph separators are valid in JSON strings but terminate a line
# in JavaScript source, so they must be escaped too.
HTML_UNSAFE: dict[str, str] = {
    "<": "\\u003c",
    ">": "\\u003e",
    "&": "\\u0026",
    " ": "\\u2028",
    " ": "\\u2029",
}

_TRANSLATION = str.maketrans(HTML_UNSAFE)


def json_for_script(data: Any) -> str:
    """Serialize ``data`` as JSON safe to inline inside a ``<script>`` block."""
    return json.dumps(data).translate(_TRANSLATION)

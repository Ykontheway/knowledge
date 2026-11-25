"""The only authorized public corpus; no business text or redaction heuristics."""

import hashlib

MARKERS = ("cobalta", "amberb", "violetc")
TEXTS = tuple(
    "".join(
        f"# Replay section {index + 1}\n\n"
        f"{marker if revision != 2 or index != 0 else 'absentcontent'} "
        f"synthetic lexical evidence revision {revision}.\n\n"
        for index, marker in enumerate(MARKERS)
    )
    for revision in range(4)
)
# The loader normalizes trailing blank lines to one newline.
TEXTS = tuple(text.rstrip() + "\n" for text in TEXTS)
DOCUMENT_TEXTS = {hashlib.sha256(text.encode()).hexdigest(): text for text in TEXTS}
SEGMENTS = frozenset(
    (checksum, start, end, text[start:end])
    for checksum, text in DOCUMENT_TEXTS.items()
    for start, end in zip(
        [0, text.index("# Replay section 2"), text.index("# Replay section 3")],
        [text.index("# Replay section 2"), text.index("# Replay section 3"), len(text)],
        strict=True,
    )
)

"""#305: the terms guard — every `\\term{key}` / `\\termas{key}{...}` a chapter
uses is defined in terms.yaml, and every terms.yaml entry is used by some
chapter (a stale glossary is the GuideNamesTests allowlist lesson in
another form). Runs over the hand-written sources under tex/, never the
generated fragments.
"""
import glob
import os
import re

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
METHODS = os.path.normpath(os.path.join(HERE, ".."))
TEX = os.path.join(METHODS, "tex")
TERMS = os.path.join(METHODS, "terms.yaml")

REFERENCE = re.compile(r"\\term(?:as)?\{([a-z0-9-]+)\}")


def chapter_sources():
    files = sorted(glob.glob(os.path.join(TEX, "*.tex")))
    assert files, f"no chapter sources under {TEX} — a scan over nothing is a vacuous green"
    return files


def references():
    found = {}
    for path in chapter_sources():
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.lstrip().startswith("%"):
                    continue
                for key in REFERENCE.findall(line):
                    found.setdefault(key, set()).add(os.path.basename(path))
    return found


def terms():
    with open(TERMS, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["terms"]


def test_every_reference_is_defined():
    defined = {t["key"] for t in terms()}
    undefined = {k: sorted(v) for k, v in references().items() if k not in defined}
    assert not undefined, f"chapters reference terms terms.yaml does not define: {undefined}"


def test_every_term_is_used():
    used = set(references())
    unused = sorted(t["key"] for t in terms() if t["key"] not in used)
    assert not unused, f"terms.yaml entries no chapter uses: {unused}"


def test_every_entry_is_complete():
    keys = [t["key"] for t in terms()]
    assert len(keys) == len(set(keys)), "duplicate keys"
    for t in terms():
        for field in ("term", "technical", "plain"):
            assert t.get(field, "").strip(), f"{t['key']}: empty {field}"
        assert re.fullmatch(r"[a-z][a-z0-9-]*", t["key"]), f"bad key {t['key']!r}"
        for field in ("technical", "plain"):
            assert not HEARING.search(t[field]), \
                f"{t['key']}.{field} asserts hearing — the guide's rule: measured, never heard"


# The guide's hearing rule (#200): a chapter states what was measured, never
# what would be heard. Three classes pass — a frequency BAND named "the
# audible band", listening that is measured, and a DISCLAIMER that the
# measured is not the heard. The disclaimers are allowlisted by exact
# phrase, every entry used, the GuideNamesTests shape.
HEARING = re.compile(r"\b(sounds?|hears?|hearing|heard|noticeabl\w*)\b|\baudib\w*\b(?! band)")
HEARING_ALLOWLIST = [
    "It does not describe what any measurement sounds like.",
    "whether it can be heard is a question the",
    "distortion sounds like.",
    "measurement sounds like: the instrument measures, and listening is yours.",
    "nothing in this document says what a measurement sounds like.",
    # The app's own disclaimer, quoted as such (the Waveform Matrix chapter;
    # #200's third class — a disclaimer that the measured is not the heard).
    "a visibly different wave is not automatically an audibly different one",
]


def test_chapters_state_what_was_measured_never_what_is_heard():
    hits = {}
    used = set()
    for path in chapter_sources():
        with open(path, encoding="utf-8") as f:
            for number, line in enumerate(f, 1):
                text = line.strip()
                if text.startswith("%"):
                    text = text.lstrip("% ")
                if not HEARING.search(text):
                    continue
                allowed = [a for a in HEARING_ALLOWLIST if a in text]
                if allowed:
                    used.update(allowed)
                    continue
                hits[f"{os.path.basename(path)}:{number}"] = text
    assert not hits, f"hearing asserted of a measurement: {hits}"
    unused = [a for a in HEARING_ALLOWLIST if a not in used]
    assert not unused, f"allowlist entries no chapter line uses: {unused}"


# The names rule (legal advice 2026-09-01): the documents name no third-party
# product. The ONE pinned list is App/PedalScopeTests/PinnedThirdPartyNames.json
# (read by ShippedNamesTests over the binary and GuideNamesTests over the
# guide); this scan reads it by repo path and applies GuideNamesTests'
# matching — word-bounded, case-insensitive, a multi-word name also matching
# hyphen-joined — over EVERY line of both .tex files, comment lines included
# (a comment ships in the open-source tree). No allowlist: neither document
# has a cable in it, so "TS" the connector never needs to appear.
REPO = os.path.normpath(os.path.join(METHODS, "..", ".."))
PINNED_NAMES = os.path.join(REPO, "App", "PedalScopeTests", "PinnedThirdPartyNames.json")


def pinned_names():
    import json
    with open(PINNED_NAMES, encoding="utf-8") as f:
        names = json.load(f)["names"]
    assert names, f"{PINNED_NAMES} lists no names — a scan over nothing is a vacuous green"
    return names


def name_pattern(name):
    """GuideNamesTests.pattern(for:), in Python."""
    words = [re.escape(w) for w in name.split(" ")]
    return re.compile(r"(?<![A-Za-z0-9])" + r"[ \-]".join(words) + r"(?![A-Za-z0-9])", re.IGNORECASE)


def test_no_third_party_names():
    patterns = [(n, name_pattern(n)) for n in pinned_names()]
    hits = {}
    for path in chapter_sources():
        with open(path, encoding="utf-8") as f:
            for number, line in enumerate(f, 1):
                found = [n for n, p in patterns if p.search(line)]
                if found:
                    hits[f"{os.path.basename(path)}:{number}"] = (found, line.strip())
    assert not hits, f"a third-party product is named: {hits}"

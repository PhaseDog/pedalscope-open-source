"""#428: the format guard for the two "Changes since the previous version"
appendices and the title-page stamp — the methods documents' counterpart of
the guide's WhatsNewTests.

The documents are RELEASE documents: the site's /methods/ and the public
copy are built from a methods release tag (methods-X.Y-rN), and each
release adds an entry, newest first, to both appendices. What is pinned:

- each appendix carries its unnumbered heading once, and every entry heading
  has the shape ``\\subsection*{X.Y (N) --- D Month YYYY}``, with a body;
- builds strictly descend and dates never increase;
- the two appendices list the same releases (the technical and the plain
  entry are written together);
- tex/release.tex's stamp names the newest entry — its build and its date —
  whether it is a release (a methods tag) or a draft (main, between
  releases), and the two statuses word the title page differently;
- both documents input the stamp, date the title page with it, and input
  their appendix once.
"""
import datetime
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
TEX = os.path.normpath(os.path.join(HERE, "..", "tex"))

SECTION = r"\section*{Changes since the previous version}"
TOC_LINE = r"\addcontentsline{toc}{section}{Changes since the previous version}"
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
HEADING = re.compile(r"^\\subsection\*\{(\d+)\.(\d+) \((\d+)\) --- (\d{1,2}) ([A-Z][a-z]+) (\d{4})\}$")
ANY_SUBSECTION = re.compile(r"\\subsection\*?\{")
MACRO = re.compile(r"^\\newcommand\{\\(release[a-z]+)\}\{(.*)\}\s*$")


def read(name):
    with open(os.path.join(TEX, name), encoding="utf-8") as f:
        return f.read()


def entries(text, name="appendix"):
    """[(version, build, date, body)] in file order; raises on a malformed file."""
    lines = [l for l in text.splitlines() if not l.lstrip().startswith("%")]
    assert sum(l.strip() == SECTION for l in lines) == 1, f"{name}: {SECTION} must appear exactly once"
    assert sum(l.strip() == TOC_LINE for l in lines) == 1, f"{name}: the table-of-contents line must appear exactly once"
    found, current = [], None
    for line in lines:
        if ANY_SUBSECTION.search(line):
            m = HEADING.match(line.strip())
            assert m, f"{name}: entry heading {line.strip()!r} is not '\\subsection*{{X.Y (N) --- D Month YYYY}}'"
            major, minor, build, day, month, year = m.groups()
            assert month in MONTHS, f"{name}: {month!r} is not a month"
            date = datetime.date(int(year), MONTHS.index(month) + 1, int(day))
            current = [f"{major}.{minor}", int(build), date, []]
            found.append(current)
        elif current is not None:
            current[3].append(line)
    assert found, f"{name}: no entries — the appendix must carry at least the release it ships with"
    for version, build, date, body in found:
        assert any(l.strip() and l.strip() != r"\end{itemize}" for l in body), \
            f"{name}: the entry for {version} ({build}) has no body"
    return [(v, b, d) for v, b, d, _ in found]


def check_order(listed, name="appendix"):
    for (v1, b1, d1), (v2, b2, d2) in zip(listed, listed[1:]):
        assert b1 > b2, f"{name}: builds must strictly descend — {v1} ({b1}) is listed above {v2} ({b2})"
        assert d1 >= d2, f"{name}: dates must not increase down the list — {d1} above {d2}"


def stamp():
    macros = {}
    for line in read("release.tex").splitlines():
        m = MACRO.match(line)
        if m:
            macros[m.group(1)] = m.group(2)
    for key in ("releasestatus", "releasebuild", "releasedate", "releasestamp"):
        assert key in macros, f"release.tex defines no \\{key}"
    return macros


def test_each_appendix_is_well_formed_and_newest_first():
    for name in ("changes-methods.tex", "changes-explained.tex"):
        check_order(entries(read(name), name), name)


def test_both_appendices_list_the_same_releases():
    m = entries(read("changes-methods.tex"), "changes-methods.tex")
    e = entries(read("changes-explained.tex"), "changes-explained.tex")
    assert m == e, f"the appendices list different releases: methods {m}, explained {e}"


def test_the_stamp_names_the_newest_entry():
    s = stamp()
    version, build, date = entries(read("changes-methods.tex"))[0]
    assert s["releasebuild"] == f"{version} ({build})", \
        f"release.tex's build {s['releasebuild']!r} is not the newest entry's {version} ({build})"
    want = f"{date.day} {MONTHS[date.month - 1]} {date.year}"
    assert s["releasedate"] == want, f"release.tex's date {s['releasedate']!r} is not the newest entry's {want!r}"
    assert s["releasestatus"] in ("release", "draft"), f"release status {s['releasestatus']!r} is neither release nor draft"
    assert r"\releasebuild" in s["releasestamp"], "the stamp does not print the build"
    if s["releasestatus"] == "release":
        assert r"\releasedate" in s["releasestamp"] and "Describes" in s["releasestamp"], \
            "a release stamp says which build it describes and the date it was published"
        assert "draft" not in s["releasestamp"].lower()
    else:
        assert "not a published release" in s["releasestamp"], \
            "a draft stamp must say it is not a published release"


def test_both_documents_carry_the_stamp_and_their_appendix():
    for doc, appendix in (("methods.tex", "changes-methods"), ("explained.tex", "changes-explained")):
        text = read(doc)
        assert text.count(r"\input{release}") == 1, f"{doc} must \\input{{release}} once"
        assert text.count(r"\date{\releasestamp}") == 1, f"{doc} must date its title page with \\releasestamp"
        assert text.count(r"\input{" + appendix + "}") == 1, f"{doc} must \\input{{{appendix}}} once"


def test_the_guard_refuses_what_it_exists_to_refuse():
    """The checks above pass on the committed files; this proves they can
    fail — each malformed appendix below must be refused."""
    good = "\n".join([SECTION, TOC_LINE,
                      r"\subsection*{1.2 (50) --- 3 November 2026}", "text",
                      r"\subsection*{1.1 (43) --- 30 September 2026}", "text"])
    check_order(entries(good))
    bad_cases = {
        "ascending builds": good.replace("1.2 (50)", "1.0 (41)"),
        "bad heading": good.replace("--- 3 November", "- 3 November"),
        "no month": good.replace("November", "Novembre"),
        "missing section": good.replace(SECTION, ""),
        "empty body": good.replace("text\n" + r"\subsection*{1.1", "\n" + r"\subsection*{1.1"),
    }
    for label, text in bad_cases.items():
        try:
            check_order(entries(text))
        except AssertionError:
            continue
        raise AssertionError(f"the guard accepted a malformed appendix ({label})")

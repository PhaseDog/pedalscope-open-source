"""#306 chapter five: the module-name guard — no module under py/ takes a
name the standard library uses OR WILL USE.

The mechanism it prevents, 2026-09-21: `py/compression.py` shadowed Python
3.14's new standard-library `compression` package (`compression.zstd`,
`compression._common`, ...) on CI's ubuntu runner, and a stdlib import made
from inside the figure code resolved to our module instead — "No module
named 'compression._common'; 'compression' is not a package". The Studio's
Python 3.13 has no such package, so the suite was green locally and red on
the push. The module is `compression_curve.py` now.

The running interpreter's `sys.stdlib_module_names` cannot see a FUTURE
CPython's additions, so the check is that list UNION a pinned set of names
newer releases have added, each with its provenance. A name in the union
is a stop for a new module, whatever the developer's interpreter says.
"""
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Standard-library top-level names added by CPython releases NEWER than
# the interpreters this suite has run on. Keep the provenance beside each.
NEWER_STDLIB_NAMES = {
    "compression",  # Python 3.14 (PEP 784): compression.zstd and the
    #                 re-homed bz2 / gzip / lzma / zlib — the 2026-09-21 case
}


def module_basenames():
    files = sorted(glob.glob(os.path.join(HERE, "*.py")))
    assert files, f"no modules under {HERE} — a scan over nothing is a vacuous green"
    return sorted(os.path.splitext(os.path.basename(p))[0] for p in files)


def test_no_module_takes_a_standard_library_name():
    reserved = set(sys.stdlib_module_names) | NEWER_STDLIB_NAMES
    offenders = [name for name in module_basenames() if name in reserved]
    assert not offenders, (
        f"module name(s) shadow the standard library on some interpreter: "
        f"{offenders} — rename (running Python {sys.version.split()[0]}; "
        f"pinned newer names {sorted(NEWER_STDLIB_NAMES)})"
    )


def test_the_pinned_set_is_not_already_visible_to_this_interpreter():
    """The pinned set exists for names the running interpreter cannot see.
    Once every interpreter the suite runs on has a name, it is in
    `sys.stdlib_module_names` and its pin is redundant — drop it then, so
    the set stays a list of FUTURE names with a reason each."""
    if sys.version_info >= (3, 14):
        assert "compression" in sys.stdlib_module_names
    else:
        assert "compression" not in sys.stdlib_module_names

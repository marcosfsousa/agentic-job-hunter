"""Runtime output must be ASCII-safe — a static scan of `src/`, not a behaviour test.

Text we write to stdout/stderr is encoded with the stream's encoding, and where that is
a legacy 8-bit codepage rather than UTF-8, a character outside it raises
`UnicodeEncodeError` mid-write and takes the run with it.

Which characters are fatal depends on the codepage, and #61's two markers land on
opposite sides of that line — worth stating precisely, because the issue itself did not:

    cp1252 (redirected stdout, Western Windows)  `—` encodes to 0x97 — SAFE
                                                 `→` has no mapping   — RAISES
    cp850 / cp437 (legacy console codepages)     both RAISE
    ascii (POSIX locale, e.g. a bare container)  both RAISE

So the arrows in `db.py`, `hard_filter.py` and `evaluator.py` were the sites actually
breaking a redirected Windows run; the em dashes needed a narrower codepage or an
ASCII locale to bite. Both are fixed, and the invariant is the simple one — runtime
output is ASCII — because a rule that depends on remembering which of two dashes cp1252
happens to include is a rule that will be got wrong.

Under a UTF-8 console, or a Linux CI with a UTF-8 locale, none of these are visible at
all. That asymmetry is why the suite was green on every one of them for months (#59, #61).

Two mechanisms cover this, and they cover different halves:

  1. `_force_utf8_streams()` in `run.py` pins the streams themselves. This is the half
     that matters for text we do not author — freelancermap is a German board, so a
     title like `Softwareentwickler für ...` reaches the same stream no matter how
     clean our own literals are.
  2. This test keeps the literals ASCII. Belt to that braces, and it is the half that
     survives someone calling into the package without going through `run.py`'s entry
     point (an import from a notebook, a future `main()` shim, a test harness).

Known limit, stated so nobody reads a green run as more than it is: the scan looks at
literals appearing *at* the sink. A marker that reaches stdout through a variable —
`label = f"{title} — {company}"` on one line and `print(label)` on another, which is
exactly the shape of the #61 site at `run.py:52` — is not caught here. Mechanism 1 is
what covers that residue. Widening this scan to chase assignments would mean a dataflow
analysis, and the honest cost/benefit says pin the stream instead.
"""
from __future__ import annotations

import ast
import io
import sys
from pathlib import Path

import pytest

from jobscout.run import _force_utf8_streams

_SRC_ROOT = Path(__file__).resolve().parent.parent / "src"

# Functions whose string arguments end up on stdout/stderr.
_BUILTIN_SINKS = {"print", "input"}
_LOGGING_SINKS = {
    "debug", "info", "warning", "error", "exception", "critical", "log", "basicConfig",
}
# argparse renders these on `--help` and on usage errors.
_ARGPARSE_SINKS = {"ArgumentParser", "add_argument", "add_parser", "add_argument_group"}

# `-` for an em dash, `->` for an arrow. Both are what #61 landed.
_ADVICE = (
    "Runtime output must be ASCII: this string reaches stdout/stderr, and a legacy "
    "codepage there (cp1252 on redirected Windows stdout, cp850/cp437 on a legacy "
    "console, ascii under a POSIX locale) raises UnicodeEncodeError mid-run on a "
    "character it cannot map. Use '-' for an em dash and '->' for an arrow. Comments "
    "and docstrings are exempt — they are never written to a stream."
)


def _is_sink(node: ast.Call) -> bool:
    """True if this call writes its string arguments to stdout or stderr."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in _BUILTIN_SINKS or func.id in _ARGPARSE_SINKS
    if isinstance(func, ast.Attribute):
        return func.attr in _LOGGING_SINKS or func.attr in _ARGPARSE_SINKS
    return False


def _non_ascii_strings(node: ast.AST) -> list[tuple[int, str]]:
    """Every non-ASCII string constant in a subtree, as (line, value).

    f-strings arrive as `JoinedStr` whose literal segments are plain `Constant`s, so
    walking the subtree covers both them and implicitly concatenated strings (which
    the parser has already merged into one node).
    """
    found = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            if not child.value.isascii():
                found.append((child.lineno, child.value))
    return found


def _offenders(source: str, label: str) -> list[str]:
    """Non-ASCII literals at stdout/stderr sinks, as human-readable locations."""
    tree = ast.parse(source)
    hits: dict[tuple[int, str], None] = {}

    for node in ast.walk(tree):
        # A raise reaches stderr through the traceback, so its message counts.
        if isinstance(node, ast.Raise) and node.exc is not None:
            for line, value in _non_ascii_strings(node.exc):
                hits[(line, value)] = None
        elif isinstance(node, ast.Call) and _is_sink(node):
            for line, value in _non_ascii_strings(node):
                hits[(line, value)] = None

    return [
        f"{label}:{line}: {sorted({hex(ord(c)) for c in value if ord(c) > 127})} in {value!r}"
        for line, value in sorted(hits)
    ]


def test_runtime_output_literals_are_ascii():
    offenders: list[str] = []
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        offenders.extend(
            _offenders(
                path.read_text(encoding="utf-8"),
                path.relative_to(_SRC_ROOT.parent).as_posix(),
            )
        )
    assert not offenders, _ADVICE + "\n\n" + "\n".join(offenders)


def test_the_scan_actually_bites():
    """Guards the guard: prove the scan flags each sink shape it claims to cover.

    Without this, a wrong `_SRC_ROOT`, a typo in the sink names, or an `ast` API drift
    would make the assertion above pass by finding nothing — which is indistinguishable
    from a clean tree. That failure mode is precisely what #59 shipped: a sweep that
    grepped for the wrong character reported success on four sites it never looked at.
    """
    sample = (
        'import logging\n'
        'logger = logging.getLogger(__name__)\n'
        'def f(parser, n, total):\n'
        '    print("done — ok")\n'
        '    logger.info("filter: %d → %d", n, total)\n'
        '    logging.basicConfig(format="%(name)s — %(message)s")\n'
        '    parser.add_argument("--x", help="fetch — but skip writes")\n'
        '    raise ValueError(f"broken — {n} rows")\n'
    )
    lines = sorted(int(o.split(":")[1]) for o in _offenders(sample, "sample.py"))
    assert lines == [4, 5, 6, 7, 8]


def test_the_scan_leaves_non_stream_text_alone():
    """The scope line from #61: text that never reaches a stream is not runtime output.

    Comments and docstrings are the obvious cases. The email subject is the instructive
    one — it carries an em dash today and keeps it, because it travels to the Resend API
    as UTF-8 JSON and never touches stdout. Same for the digest markdown, which
    `writer.py` writes with an explicit `encoding="utf-8"`.

    If this ever fails, the scan has widened past what `_ADVICE` tells the reader, and
    the next person hits a failure they cannot act on from the message.
    """
    sample = (
        '"""Module docstring — prose."""\n'
        'def f():\n'
        '    """Does a thing: fetch → filter."""\n'
        '    # A comment — also prose.\n'
        '    subject = "JobScout Digest — 2026-07-30"\n'
        '    return subject\n'
    )
    assert _offenders(sample, "sample.py") == []


# ---------------------------------------------------------------------------
# The other half: the stream itself
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "encoding, unencodable",
    [
        # The two codepages differ in what they reject, and #61's two marker
        # characters fall on opposite sides of that line — see the module docstring.
        ("cp1252", "filter: 22 → 4"),
        ("cp850", "Pipeline complete — 4 jobs"),
    ],
)
def test_force_utf8_streams_repins_a_legacy_codepage(monkeypatch, encoding, unencodable):
    """The case the ASCII scan cannot reach: non-ASCII text we did not author.

    A German job title through `--review`, or a query name in a log line, is data.
    `ä` survives both legacy codepages, but `–`, `„` and `…` — all of which appear
    in real freelancermap listing titles — do not survive cp850, and no amount of
    literal-scrubbing in our own source changes that. Pinning the stream does.
    """
    stdout = io.TextIOWrapper(io.BytesIO(), encoding=encoding)
    stderr = io.TextIOWrapper(io.BytesIO(), encoding=encoding)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    # Precondition: this stream really does raise as configured, so the assertion
    # below is testing the fix rather than an already-harmless stream.
    with pytest.raises(UnicodeEncodeError):
        stdout.write(unencodable)
        stdout.flush()

    _force_utf8_streams()

    assert sys.stdout.encoding == "utf-8"
    assert sys.stderr.encoding == "utf-8"
    sys.stdout.write(unencodable + " Softwareentwickler für ML")
    sys.stdout.flush()


def test_force_utf8_streams_tolerates_a_stream_without_reconfigure():
    """pytest's own capture replaces sys.stdout with an object that has no
    `reconfigure`. Blowing up there would make the entry point fail under any
    harness that wraps the streams — a worse bug than the one being fixed."""
    class _Plain:
        encoding = "cp1252"

    original_stdout, original_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = _Plain(), _Plain()
    try:
        _force_utf8_streams()  # must not raise
    finally:
        sys.stdout, sys.stderr = original_stdout, original_stderr

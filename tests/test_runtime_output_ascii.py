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
import importlib
import io
import sys
import tomllib
from pathlib import Path

import pytest

from jobscout.run import _force_utf8_streams

_SRC_ROOT = Path(__file__).resolve().parent.parent / "src"

# Functions whose string arguments end up on stdout/stderr.
_BUILTIN_SINKS = {"print", "input"}
# `warn` covers both `warnings.warn` and logging's deprecated `logger.warn` alias — any
# `.warn()` is a warning sink, so matching on the bare attribute is the useful reading.
_LOGGING_SINKS = {
    "debug", "info", "warning", "warn", "error", "exception", "critical", "log",
    "basicConfig",
}
# argparse renders these on `--help` and on usage errors.
_ARGPARSE_SINKS = {"ArgumentParser", "add_argument", "add_parser", "add_argument_group"}
# Matched on the *whole* dotted name, not the trailing attribute: `write` alone would
# flag `f.write(...)` and `path.write_text(...)`, which go to files with an explicit
# encoding and are outside this rule (see `test_the_scan_leaves_non_stream_text_alone`).
# `sys.exit("msg")` belongs here because the message is printed to stderr on the way out.
#
# `traceback.print_exc` was raised alongside these in #64 and is deliberately absent: it
# takes no author-written message, so there is no literal at that call for a scan to see.
_QUALIFIED_SINKS = {
    "sys.stdout.write", "sys.stderr.write",
    "sys.stdout.writelines", "sys.stderr.writelines",
    "sys.exit",
    "warnings.warn",
}

# `-` for an em dash, `->` for an arrow. Both are what #61 landed.
_ADVICE = (
    "Runtime output must be ASCII: this string reaches stdout/stderr, and a legacy "
    "codepage there (cp1252 on redirected Windows stdout, cp850/cp437 on a legacy "
    "console, ascii under a POSIX locale) raises UnicodeEncodeError mid-run on a "
    "character it cannot map. Use '-' for an em dash and '->' for an arrow. Comments "
    "and docstrings are exempt — they are never written to a stream."
)


def _dotted_name(node: ast.AST) -> str | None:
    """`"sys.stdout.write"` for that attribute chain; None if it is not a plain name."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _is_sink(node: ast.Call) -> bool:
    """True if this call writes its string arguments to stdout or stderr."""
    func = node.func
    if _dotted_name(func) in _QUALIFIED_SINKS:
        return True
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
        # A raise reaches stderr through the traceback and a failed assert through its
        # message, so both count even though neither is a call to a sink.
        if isinstance(node, ast.Raise) and node.exc is not None:
            subtree: ast.AST | None = node.exc
        elif isinstance(node, ast.Assert) and node.msg is not None:
            subtree = node.msg
        elif isinstance(node, ast.Call) and _is_sink(node):
            subtree = node
        else:
            continue
        for line, value in _non_ascii_strings(subtree):
            hits[(line, value)] = None

    return [
        f"{label}:{line}: {sorted({hex(ord(c)) for c in value if ord(c) > 127})} in {value!r}"
        for line, value in sorted(hits)
    ]


def test_runtime_output_literals_are_ascii():
    paths = sorted(_SRC_ROOT.rglob("*.py"))

    # Guards the guard, first half: a `_SRC_ROOT` that resolves to a missing or empty
    # directory makes the assertion below pass by scanning nothing, which is
    # indistinguishable from a clean tree — the same fail-open shape #59 shipped. The
    # sentinel is `run.py` because that is where both the sinks and the stream pin
    # live: if the scan cannot see that file, it is not looking at the package.
    # `test_repo_invariants.py` guards `git ls-files` the same way (#64).
    scanned = {p.relative_to(_SRC_ROOT).as_posix() for p in paths}
    assert "jobscout/run.py" in scanned, (
        f"the scan found {len(paths)} file(s) under {_SRC_ROOT}, and jobscout/run.py "
        "was not among them — so this test is passing without having read the package. "
        "Check that _SRC_ROOT still resolves to this tree's src/ directory."
    )

    offenders: list[str] = []
    for path in paths:
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
        'import logging, sys, warnings\n'
        'logger = logging.getLogger(__name__)\n'
        'def f(parser, n, total):\n'
        '    print("done — ok")\n'
        '    logger.info("filter: %d → %d", n, total)\n'
        '    logging.basicConfig(format="%(name)s — %(message)s")\n'
        '    parser.add_argument("--x", help="fetch — but skip writes")\n'
        '    sys.stdout.write("wrote — 3 rows")\n'
        '    warnings.warn("deprecated — use g()")\n'
        '    sys.exit("fatal — no config")\n'
        '    assert n, "n must be nonzero — got 0"\n'
        '    raise ValueError(f"broken — {n} rows")\n'
    )
    lines = sorted(int(o.split(":")[1]) for o in _offenders(sample, "sample.py"))
    assert lines == [4, 5, 6, 7, 8, 9, 10, 11, 12]


def test_the_scan_leaves_non_stream_text_alone():
    """The scope line from #61: text that never reaches a stream is not runtime output.

    Comments and docstrings are the obvious cases. The email subject is the instructive
    one — it carries an em dash today and keeps it, because it travels to the Resend API
    as UTF-8 JSON and never touches stdout. Same for the digest markdown, which
    `writer.py` writes with an explicit `encoding="utf-8"`.

    If this ever fails, the scan has widened past what `_ADVICE` tells the reader, and
    the next person hits a failure they cannot act on from the message.

    The two file writes are the negative control for `_QUALIFIED_SINKS` (#64). Matching
    a bare `write` attribute would catch `sys.stdout.write` and drag both of these in
    with it — a file opened with an explicit encoding is not a console stream, and
    that is exactly the digest-markdown case the paragraph above protects.
    """
    sample = (
        '"""Module docstring — prose."""\n'
        'def f(fh, path):\n'
        '    """Does a thing: fetch → filter."""\n'
        '    # A comment — also prose.\n'
        '    subject = "JobScout Digest — 2026-07-30"\n'
        '    fh.write("digest — written to a file handle")\n'
        '    path.write_text("digest — written to a path", encoding="utf-8")\n'
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


def test_force_utf8_streams_tolerates_a_stream_without_reconfigure(monkeypatch):
    """pytest's own capture replaces sys.stdout with an object that has no
    `reconfigure`. Blowing up there would make the entry point fail under any
    harness that wraps the streams — a worse bug than the one being fixed.

    `monkeypatch` rather than a try/finally: both restore the streams on a normal
    failure, but only the fixture restores them when the run is interrupted between
    the swap and the finally. Leaving a `_Plain` on sys.stdout would take pytest's
    own reporting down with it (#64).
    """
    class _Plain:
        encoding = "cp1252"

    monkeypatch.setattr(sys, "stdout", _Plain())
    monkeypatch.setattr(sys, "stderr", _Plain())
    _force_utf8_streams()  # must not raise


def test_console_script_entry_point_exists():
    """`[project.scripts] jobscout = "jobscout.run:main"` must resolve to a callable.

    It did not until #64: the body lived inline under `if __name__ == "__main__"`, so
    an installed `jobscout` failed at import — and, had it not, would have skipped the
    UTF-8 pin entirely, because that block does not run for an installed entry point.
    Mechanism 1 shipping disabled is the failure this test exists to catch.
    """
    entry_point = tomllib.loads(
        (_SRC_ROOT.parent / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["scripts"]["jobscout"]
    module_name, _, attribute = entry_point.partition(":")

    module = importlib.import_module(module_name)
    assert callable(getattr(module, attribute, None)), (
        f"pyproject declares the console script as {entry_point!r}, but "
        f"{module_name} has no callable {attribute!r}. An installed `jobscout` "
        "would fail at import."
    )

    # The pin has to be inside that callable, not beside it in the `__main__` block.
    tree = ast.parse((_SRC_ROOT / "jobscout" / "run.py").read_text(encoding="utf-8"))
    entry_fn = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == attribute
    )
    pinned = {
        node.func.id for node in ast.walk(entry_fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_force_utf8_streams" in pinned, (
        f"{attribute}() does not call _force_utf8_streams(). An installed run never "
        "executes the `if __name__ == \"__main__\"` block, so a pin placed only there "
        "is disabled for exactly the users who installed the package the declared way."
    )

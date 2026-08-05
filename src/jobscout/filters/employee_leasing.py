"""Prose backstop for Arbeitnehmerüberlassung (ANÜ), the pipeline's first
deterministic prose-scanning stage.

`_passes_contract_type` gates on `JobListing.contract_type`, which freelancermap
sets from its own `projectContractType.type` tag. That tag is the structured half
and it works — but it fails *open*: anything the adapter cannot map becomes
`unknown`, which passes. A posting whose leasing-only status is stated in the body
text rather than carried in the tag therefore reaches evaluation and can be
surfaced as a match. This module reads the text the tag did not carry.

Three states, because the real world has more than two:

    exclusive   the posting is leasing-only, or excludes freelancers outright
    optional    leasing is one of several engagement forms on offer
    unknown     nothing said either way — most of the corpus

Only `exclusive` is acted on here (the hard filter drops it). `optional` is
produced and returned but has no behavioural consequence yet: surfacing it is
drop-observability work and lives in its own issue. It is classified now so that
the ordering trap below is solved once, in the place that can solve it.

**The trap: `exclusive` is checked first, always.** `"nur ANÜ möglich"` contains
`"ANÜ möglich"`, so an optional-first pass reads a hard exclude as a soft pass —
the single worst outcome this module can produce, since ANÜ is a funding-level
dealbreaker rather than a preference.

No LLM call happens here and none may be added: the hard filter is deterministic
and cheap by design.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

LeasingState = Literal["exclusive", "optional", "unknown"]


@dataclass(frozen=True)
class LeasingClassification:
    """What the text said, and the cue that decided it.

    `cue` is the matched phrase as written in the cue lists below, not as it
    appeared in the posting — it names the rule that fired, which is what a drop
    log line needs to be reviewable. It is None only when `state` is "unknown".
    """
    state: LeasingState
    cue: str | None


def _compile(phrase: str) -> re.Pattern[str]:
    r"""Turn a cue phrase into a whitespace- and case-tolerant pattern.

    Three tolerances, each earned by how German job posts are actually written:

    * `\s+` between tokens, so a cue split across a line break still matches.
    * `\b` at both ends, so a cue is a phrase and not an accident inside a longer
      word. This is what keeps the short abbreviation `AÜ` from matching the middle
      of `Bauüberwachung`, and it is why this module does not reuse
      `_passes_exclude_keywords`' naive `in` test.
    * `str.casefold()` on both sides rather than `str.lower()`, which additionally
      folds `ß` to `ss` — so the cue `ausschließlich` matches a posting that spells
      it `ausschliesslich`, for free and without a second cue entry.
    """
    tokens = [re.escape(t) for t in phrase.casefold().split()]
    return re.compile(r"\b" + r"\s+".join(tokens) + r"\b")


@dataclass(frozen=True)
class _Cue:
    phrase: str
    pattern: re.Pattern[str]
    # True for a phrase that only means leasing in context. See `wahlweise` below.
    needs_leasing_term: bool = False


def _cues(*specs: tuple[str, bool]) -> tuple[_Cue, ...]:
    return tuple(_Cue(phrase, _compile(phrase), needs) for phrase, needs in specs)


# The leasing vocabulary itself, used to qualify cues that do not carry it. No
# trailing `\b`: `Arbeitnehmerüberlassung` compounds freely in German
# (`...svertrag`, `...sgesetz`), and a boundary there would miss every compound.
_LEASING_TERM = re.compile(r"\b(?:anü|aü|arbeitnehmerüberlassung)")

# Scanned to exhaustion before the optional list is opened at all — see the trap
# in the module docstring. Some of these name no engagement form and exclude the
# candidate anyway (`keine Freiberufler`); the outcome is the same, so the state is.
_EXCLUSIVE_CUES = _cues(
    ("nur ANÜ", False),
    ("ausschließlich ANÜ", False),
    ("ausschließlich Arbeitnehmerüberlassung", False),
    ("Anstellung beim Personaldienstleister", False),
    ("keine Freiberufler", False),
    ("keine Selbstständigen", False),
    ("nicht auf Freelance-Basis", False),
    ("AÜ zwingend", False),
)

# `wahlweise` ("either/or") is the one cue here that says nothing about leasing on
# its own — "wahlweise vor Ort oder remote" is a working-arrangement sentence, not
# an engagement-form one. Unqualified it would classify unrelated rows `optional`,
# which costs nothing today because `optional` and `unknown` are both kept, but
# would put wrong rows in front of the maintainer the moment drop observability
# surfaces the state. So it fires only alongside a leasing term.
_OPTIONAL_CUES = _cues(
    ("ANÜ möglich", False),
    ("AÜ oder Werkvertrag", False),
    ("ANÜ oder Freiberuflich", False),
    ("auch ANÜ", False),
    ("wahlweise", True),
)


# The precedence itself, as data rather than as control flow, so that the one
# ordering constraint this module has cannot be reversed by an edit that merely
# looks like a reordering. `exclusive` before `optional`, always.
_BY_PRECEDENCE: tuple[tuple[LeasingState, tuple[_Cue, ...]], ...] = (
    ("exclusive", _EXCLUSIVE_CUES),
    ("optional", _OPTIONAL_CUES),
)


def classify_employee_leasing(text: str) -> LeasingClassification:
    """Classify a posting's engagement form from its prose.

    `text` is whatever the caller considers the posting's words. The hard filter
    passes title and description together, matching every other text predicate
    there — a title reading `ML Engineer (nur ANÜ)` is as binding as a body that
    says so, and reading only one of the two would be an arbitrary blind spot.
    """
    haystack = text.casefold()
    has_leasing_term = _LEASING_TERM.search(haystack) is not None

    for state, cues in _BY_PRECEDENCE:
        for cue in cues:
            if cue.needs_leasing_term and not has_leasing_term:
                continue
            if cue.pattern.search(haystack):
                return LeasingClassification(state, cue.phrase)

    return LeasingClassification("unknown", None)

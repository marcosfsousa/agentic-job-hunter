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
dealbreaker rather than a preference. Precedence is what closes it, not the shape
of the cues: `"nur über ANÜ möglich"` matches an exclusive cue and an optional one
simultaneously, and only the ordering decides which wins.

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


# A filler word may sit inside a cue's gaps — `nur ANÜ` has to match `nur über ANÜ`
# and `AÜ zwingend` has to match `AÜ ist zwingend`. Two things bound how far that
# reaches, because a gap that swallows too much stops meaning what the cue means:
#
# 1. **No negator may sit in a gap.** A cue asserts something; a negator inside it
#    asserts the opposite, and the match would read the posting exactly backwards.
#    `Eine AÜ ist nicht zwingend erforderlich` is a posting saying leasing is *not*
#    required, and without this it matched `AÜ zwingend` and was dropped.
# 2. **`\w+\s+` cannot cross punctuation**, so a filler runs out at the first comma
#    or full stop rather than reaching across a clause.
#
# Widths are per cue rather than global — see `_EXCLUSIVE_CUES`.
_NEGATORS = ("nicht", r"kein\w*", "ohne", "weder", "statt", "sondern", "nie", "niemals")
_NOT_A_NEGATOR = "(?!(?:" + "|".join(rf"{n}\b" for n in _NEGATORS) + "))"


def _compile(phrase: str, *, gap: int) -> re.Pattern[str]:
    r"""Turn a cue phrase into a whitespace-, case- and filler-tolerant pattern.

    The tolerances are what make a written cue match how a posting actually spells
    it. Each is bounded, and the bounds are set by the module's governing
    asymmetry: a false `exclusive` costs one listing, while a false `unknown` puts
    leasing-only work in front of the maintainer, which is the funding-level
    failure this stage exists to prevent. So the default is to widen — but not
    past the point where the match stops meaning what the cue means, which is what
    the negator guard and the per-cue width are for.

    * `\s+` between tokens, so a cue split across a line break still matches.
    * `\b` at the **start** only. A leading boundary is what keeps a cue from
      matching inside a longer word, and it is why this module does not reuse
      `_passes_exclude_keywords`' naive `in` test. A *trailing* boundary is the
      one that must not be there: German compounds freely, so
      `ausschließlich Arbeitnehmerüberlassungsverträge` is the same statement as
      `ausschließlich Arbeitnehmerüberlassung`, and a closing `\b` reads it as
      `unknown` and surfaces the row.
    * up to `gap` non-negating words at each internal gap — see above.
    * `str.casefold()` on both sides rather than `str.lower()`, which additionally
      folds `ß` to `ss` — so the cue `ausschließlich` matches a posting that spells
      it `ausschliesslich`, for free and without a second cue entry.
    """
    tokens = [re.escape(t) for t in phrase.casefold().split()]
    joiner = r"\s+" + (rf"(?:{_NOT_A_NEGATOR}\w+\s+){{0,{gap}}}" if gap else "")
    return re.compile(r"\b" + joiner.join(tokens))


@dataclass(frozen=True)
class _Cue:
    phrase: str
    pattern: re.Pattern[str]
    # True for a phrase that only means leasing in context. See `wahlweise` below.
    needs_leasing_term: bool = False


def _cues(*specs: tuple[str, int, bool]) -> tuple[_Cue, ...]:
    return tuple(
        _Cue(phrase, _compile(phrase, gap=gap), needs) for phrase, gap, needs in specs
    )


# The leasing vocabulary itself, used to qualify cues that do not carry it, and to
# widen the restrictive cues below past whatever noun the posting attaches it to.
_LEASING_TERM = re.compile(r"\b(?:anü|aü|arbeitnehmerüberlassung)")

# Scanned to exhaustion before the optional list is opened at all — see the trap
# in the module docstring. Some of these name no engagement form and exclude the
# candidate anyway (`keine Freiberufler`); the outcome is the same, so the state is.
#
# The `gap` column is how many filler words the cue tolerates, and two rows are
# deliberately narrower than the rest:
#
# * `nicht auf Freelance-Basis` takes **none**. Its first word is already a
#   negator, so the guard above cannot help it: a filler there produces
#   `nicht nur auf Freelance-Basis`, which states the opposite.
# * The `keine ...` rows take **one**. Their first word is a negative quantifier
#   looking for a noun to attach to, and a second filler lets it reach past the one
#   the cue names to a different one — `keine Kosten für Freiberufler` is a posting
#   welcoming freelancers, and at width two it matched `keine Freiberufler` and was
#   dropped. One filler still admits the adjective that motivated the width
#   (`keine externen Freiberufler`); two is where the noun phrase changes.
_EXCLUSIVE_CUES = _cues(
    #  phrase                                   gap  needs_leasing_term
    ("nur ANÜ",                                 2,   False),
    ("ausschließlich ANÜ",                      2,   False),
    ("ausschließlich Arbeitnehmerüberlassung",  2,   False),
    ("Anstellung beim Personaldienstleister",   2,   False),
    ("keine Freiberufler",                      1,   False),
    ("keine Selbstständigen",                   1,   False),
    ("nicht auf Freelance-Basis",               0,   False),
    ("AÜ zwingend",                             2,   False),
)

# `wahlweise` ("either/or") is the one cue here that says nothing about leasing on
# its own — "wahlweise vor Ort oder remote" is a working-arrangement sentence, not
# an engagement-form one. Unqualified it would classify unrelated rows `optional`,
# which costs nothing today because `optional` and `unknown` are both kept, but
# would put wrong rows in front of the maintainer the moment drop observability
# surfaces the state. So it fires only alongside a leasing term.
_OPTIONAL_CUES = _cues(
    ("ANÜ möglich",                             2,   False),
    ("AÜ oder Werkvertrag",                     2,   False),
    ("ANÜ oder Freiberuflich",                  2,   False),
    ("auch ANÜ",                                2,   False),
    ("wahlweise",                               0,   True),
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

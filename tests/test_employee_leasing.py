"""Tests for the ANÜ prose classifier.

Pure string work — no fixtures, no config, no network, and by construction no LLM
call, which is the point: this stage is deterministic or it does not belong in the
hard filter.

Every case below is a sentence in the shape a German posting actually writes it,
rather than the bare cue phrase. A cue list tested against itself proves only that
`in` works; tested against prose it proves the cue survives the words around it.
"""
from __future__ import annotations

import pytest

from jobscout.filters.employee_leasing import (
    _EXCLUSIVE_CUES,
    _OPTIONAL_CUES,
    classify_employee_leasing,
)

# (posting text, expected state, expected cue). One row per cue in the module's
# two lists — `TestCueCoverage` below fails if that stops being true.
_CASES = [
    # --- exclusive ---------------------------------------------------------
    ("Die Zusammenarbeit erfolgt nur ANÜ, eine andere Form ist ausgeschlossen.",
     "exclusive", "nur ANÜ"),
    ("Die Position wird ausschließlich ANÜ besetzt.",
     "exclusive", "ausschließlich ANÜ"),
    ("Wir besetzen ausschließlich Arbeitnehmerüberlassung, bitte um Verständnis.",
     "exclusive", "ausschließlich Arbeitnehmerüberlassung"),
    ("Es erfolgt eine Anstellung beim Personaldienstleister für die Projektdauer.",
     "exclusive", "Anstellung beim Personaldienstleister"),
    ("Bitte beachten Sie: keine Freiberufler für dieses Mandat.",
     "exclusive", "keine Freiberufler"),
    ("Wir berücksichtigen keine Selbstständigen in diesem Verfahren.",
     "exclusive", "keine Selbstständigen"),
    ("Das Projekt wird nicht auf Freelance-Basis vergeben.",
     "exclusive", "nicht auf Freelance-Basis"),
    ("AÜ zwingend erforderlich, der Kunde lässt nichts anderes zu.",
     "exclusive", "AÜ zwingend"),
    # --- optional ----------------------------------------------------------
    ("Einsatz als Freiberufler oder ANÜ möglich, ganz nach Ihrem Wunsch.",
     "optional", "ANÜ möglich"),
    ("Die Abwicklung erfolgt über AÜ oder Werkvertrag.",
     "optional", "AÜ oder Werkvertrag"),
    ("ANÜ oder Freiberuflich, beides ist für uns denkbar.",
     "optional", "ANÜ oder Freiberuflich"),
    ("Neben dem Werkvertrag bieten wir auch ANÜ an.",
     "optional", "auch ANÜ"),
    ("Wahlweise ist eine Abwicklung über ANÜ denkbar.",
     "optional", "wahlweise"),
]


class TestCues:
    @pytest.mark.parametrize("text, state, cue", _CASES)
    def test_cue_classifies_and_names_itself(self, text, state, cue):
        verdict = classify_employee_leasing(text)
        assert verdict.state == state
        # The returned cue is asserted too, not just the state. A row that lands in
        # the right state via the wrong cue is a drop the log line would misexplain,
        # and within a list it is also how precedence between cues stays visible.
        assert verdict.cue == cue


class TestCueCoverage:
    def test_every_declared_cue_has_a_case(self):
        """The acceptance criterion, as a test rather than as a review step.

        Adding a cue to either list without adding a sentence here fails this,
        which is the only way "every cue has a test" survives the next edit.
        """
        declared = {c.phrase for c in _EXCLUSIVE_CUES + _OPTIONAL_CUES}
        covered = {cue for _, _, cue in _CASES}
        assert declared == covered


class TestExclusiveWinsOverOptional:
    def test_nur_anue_moeglich_is_exclusive(self):
        """The named trap case, verbatim from the issue.

        `"nur ANÜ möglich"` contains `"ANÜ möglich"`. An optional-first scan reads
        a funding-level dealbreaker as a soft pass, which is the worst outcome this
        module has available to it.
        """
        verdict = classify_employee_leasing("Der Einsatz ist nur ANÜ möglich.")
        assert verdict.state == "exclusive"
        assert verdict.cue == "nur ANÜ"

    def test_an_exclusive_cue_wins_from_anywhere_in_the_text(self):
        """Precedence is over the whole text, not over reading order.

        Here the optional cue comes first in the posting and the exclusive one is
        appended as a correction two sentences later — the order a real posting
        edits itself in. A first-match-wins scan over the text would keep this row.
        """
        text = (
            "Einsatz als Freiberufler oder ANÜ möglich. "
            "Update vom Kunden: keine Freiberufler."
        )
        assert classify_employee_leasing(text).state == "exclusive"


class TestWriteVariants:
    def test_case_is_ignored(self):
        assert classify_employee_leasing("NUR ANÜ MÖGLICH").state == "exclusive"

    def test_sharp_s_is_folded(self):
        """`casefold()` maps ß to ss, so one cue covers both spellings."""
        assert classify_employee_leasing(
            "Die Position wird ausschliesslich ANÜ besetzt."
        ).state == "exclusive"

    def test_a_cue_split_across_a_line_break_still_matches(self):
        assert classify_employee_leasing(
            "Das Projekt wird nicht auf\nFreelance-Basis vergeben."
        ).state == "exclusive"


class TestUnknown:
    def test_silent_posting_is_unknown_with_no_cue(self):
        verdict = classify_employee_leasing(
            "Wir suchen Verstärkung für ein LLM-Projekt, remote, ab sofort."
        )
        assert verdict.state == "unknown"
        assert verdict.cue is None

    def test_a_bare_mention_of_the_term_decides_nothing(self):
        """`Arbeitnehmerüberlassung` alone is untagged, which is `unknown`.

        The states are about what the posting *committed* to. A term appearing in
        passing — here as domain experience being asked for — is neither a hard
        exclude nor an offer, and treating it as either would misread most of the
        corpus that mentions it at all.
        """
        assert classify_employee_leasing(
            "Erfahrung mit Arbeitnehmerüberlassung im HR-Umfeld von Vorteil."
        ).state == "unknown"


class TestWahlweiseIsQualified:
    def test_wahlweise_without_a_leasing_term_is_unknown(self):
        """"wahlweise" is an ordinary German adverb before it is a cue.

        Unqualified it fires on working-arrangement sentences that say nothing
        about the engagement form. Free today, since `optional` and `unknown` are
        both kept — but wrong the moment drop observability surfaces the state.
        """
        assert classify_employee_leasing(
            "Die Arbeit erfolgt wahlweise vor Ort oder remote."
        ).state == "unknown"

    def test_a_leasing_term_inside_a_longer_word_does_not_qualify_it(self):
        """The word boundary, asserted where its absence would actually show.

        `Bauüberwachung` contains the letters of the abbreviation `AÜ`. Without
        `\\b` on the leasing term, this row qualifies `wahlweise` and comes back
        `optional` — a naive substring test of the kind `_passes_exclude_keywords`
        uses would do exactly that.
        """
        assert classify_employee_leasing(
            "Wahlweise Unterstützung bei der Bauüberwachung."
        ).state == "unknown"

    def test_a_compound_of_the_full_term_does_qualify_it(self):
        """...and the boundary is deliberately one-sided.

        German compounds freely, so `Arbeitnehmerüberlassungsvertrag` is the same
        term. A closing `\\b` would have missed every compound of it.
        """
        assert classify_employee_leasing(
            "Wahlweise über einen Arbeitnehmerüberlassungsvertrag."
        ).state == "optional"

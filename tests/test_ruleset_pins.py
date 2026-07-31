# tests/test_ruleset_pins.py
#
# The sibling `tests/test_required_checks.py` names is real. That file is a copy
# of a template maintained in github.com/marcosfsousa/gh-repo-baseline, and the
# convention is that it stays byte-identical to that template below its header,
# so anything about *this* repo's team or deployment cannot live there — it would
# be edited on every copy and would rot into an assertion nobody trusts. This is
# where those go.
#
# "Byte-identical" is the convention, not a verified fact. `TestTheCopiedGuardWasNotEdited`
# below pins the copy against *local* edits; nothing here checks it against
# upstream, which would need a network fetch. Read that class before treating its
# green tick as "we match the baseline".

"""
The decisions in ``.github/rulesets/main.json`` that are this repo's, not the
baseline's.

Both pins here are load-bearing, and neither is covered by the drift guard next
door. That guard asserts the ruleset is enforced, targets ``main``, blocks force
pushes and deletions, requires a pull request, and requires ``pytest`` — and
every one of those stays green while the two values below are changed to
something that unprotects the branch.

``bypass_actors``
    The one that matters. The ruleset grants Repository admin a bypass, and the
    whole argument for that being safe is the **mode**: ``pull_request`` lets an
    admin merge their own pull request without waiting on the gate, which leaves
    a pull request, a diff, and a merge commit to read afterwards. ``always``
    permits ``git push`` straight to ``main`` and leaves nothing.

    The two differ by one word in a JSON file and look near-identical in a diff.
    Adding a second actor is likewise a one-line change. So the count, the actor
    and the mode are all pinned: widening any of them is a real decision and
    should cost an edit here, where the reason is written down, rather than
    passing silently.

``required_approving_review_count``
    Zero, and correct — for now. GitHub does not let an author approve their own
    pull request, so on a repo with one contributor any positive count means no
    human pull request can ever merge, and the only way out is to weaken the
    ruleset under pressure. Zero is therefore not laxity; it is the only value
    that leaves the pull request requirement enforceable at all.

    It is also the value that stops being right the moment a second person has
    write access, and nothing about that day will announce itself. The assertion
    below is exact so that raising it is deliberate, and the comment on it says
    what to do.

Like the guard next door, this reads the committed JSON and not GitHub. It
cannot prove the ruleset is applied with this content — the API is the authority
and it needs admin credentials a test suite should not have. What it does prove
is that a change to the committed record is a change someone had to make here
too, which is the half that shows up in review.

One thing here is not about the ruleset at all: ``TestTheCopiedGuardWasNotEdited``
pins the integrity of the guard file next door. It lives here for the same reason
everything else does — it is a fact about *this* repo's copy, so it cannot live in
the copy itself without being overwritten by the thing it describes.
"""

import hashlib
import json
from pathlib import Path


_RULESET = Path(__file__).resolve().parent.parent / ".github" / "rulesets" / "main.json"

# GitHub's fixed id for the built-in Repository admin role. The bypass is granted
# to the *role*, not to a user, so it survives an account rename and does not
# quietly become a grant to a person who has since left.
_REPOSITORY_ADMIN = 5


def _ruleset() -> dict:
    return json.loads(_RULESET.read_text(encoding="utf-8"))


def _rule(rule_type: str) -> dict | None:
    return next(
        (r for r in _ruleset().get("rules", []) if r.get("type") == rule_type), None
    )


def _the_one_bypass() -> dict:
    """
    The single bypass actor, or a failure that names the count rather than the
    field the caller was about to read.

    The two tests that use this describe an actor that exists. Reaching them with
    none — a ruleset where ``bypass_actors`` was removed entirely, which is a
    real edit and a *tightening* — would otherwise report "the bypass mode is
    None", blaming a field nobody set for a decision someone did make.
    ``test_exactly_one_actor_may_bypass`` is where that belongs, and this points
    at it instead of guessing.

    It asserts *non-empty*, deliberately, and not ``== 1``. The count is that
    other test's job, and duplicating it here made a second grant fail three
    tests instead of one — so the message someone actually read was about the
    role or the mode of an actor that was never the problem.

    The shape is checked before the emptiness for the same reason the emptiness
    is checked before the index: a truthy non-list — a mapping, say — is truthy,
    so it would reach ``actors[0]`` and raise ``KeyError`` instead of any of the
    messages written here. ``test_bypass_actors_is_a_list_that_was_actually_read``
    owns that failure too, and this points at it rather than crashing on the way.
    """
    actors = _ruleset().get("bypass_actors", [])
    assert isinstance(actors, list), (
        f"`bypass_actors` is {actors!r}, not a list, so there is no first actor "
        "to describe.\nThat shape is "
        "test_bypass_actors_is_a_list_that_was_actually_read's to report, and its "
        "message says what to do."
    )
    assert actors, (
        "The ruleset grants no bypass at all, so there is none for this test to "
        "describe.\nThat is a real change — a tightening — but it is "
        "test_exactly_one_actor_may_bypass's to report, and its message says "
        "what to do. Nothing here can say anything useful until there is an "
        "actor to read."
    )
    return actors[0]


class TestTheBypassStaysNarrow:
    """
    The grant that makes the protected branch bypassable, held to the shape that
    makes it defensible.
    """

    def test_exactly_one_actor_may_bypass(self):
        # Asserted as a count before anything about the actor itself, so a second
        # grant fails as a second grant. Checking only that the admin entry is
        # present and correct would pass a file that had grown a second entry
        # underneath it — which is the shape this is most likely to drift into,
        # since adding is easier than editing.
        actors = _ruleset().get("bypass_actors", [])
        assert len(actors) == 1, (
            f"The ruleset grants {len(actors)} bypasses, not 1:\n"
            + "\n".join(f"  {actor}" for actor in actors)
            + "\n\nEvery bypass is a way past the gate the rest of this ruleset "
            "exists to hold. One, held to the role and mode asserted below, is "
            "the documented baseline. Granting another is a decision that should "
            "be made here in the open rather than by an extra object in a JSON "
            "file nobody re-reads."
        )

    def test_the_bypass_is_the_repository_admin_role(self):
        actor = _the_one_bypass()
        assert (actor.get("actor_type"), actor.get("actor_id")) == (
            "RepositoryRole",
            _REPOSITORY_ADMIN,
        ), (
            f"The bypass is granted to {actor.get('actor_type')!r} "
            f"{actor.get('actor_id')!r}, not to the Repository admin role "
            f"({_REPOSITORY_ADMIN}).\n"
            "Granted to the role, the bypass follows whoever administers the repo "
            "and disappears with the role. Granted to an Integration or a "
            "specific user id it outlives the reason it was created, and an id in "
            "JSON does not read as a name anyone recognises."
        )

    def test_the_bypass_cannot_push_straight_to_main(self):
        # The assertion this whole file was written for. `always` is one word
        # away in the same field, and it converts "merge your own pull request
        # without waiting for CI" into "push to main with no pull request at
        # all". Every other test in this repo — including the entire drift guard
        # next door — stays green through that change.
        mode = _the_one_bypass().get("bypass_mode")
        assert mode == "pull_request", (
            f"The bypass mode is {mode!r}, not 'pull_request'.\n"
            "`always` permits a direct push to the protected branch, leaving no "
            "pull request and no diff to review after the fact. `pull_request` "
            "keeps the pull request mandatory and only lets an admin merge it "
            "without the gate going green — the emergency path still leaves a "
            "trail, which is the entire reason this bypass is considered safe.\n\n"
            "If a direct push is genuinely needed, that is a bigger decision than "
            "this field: say so in CLAUDE.md, which currently forbids it outright."
        )


class TestTheApprovalCountIsDeliberate:

    def test_no_approvals_are_required(self):
        # Exact, and pinned low on purpose — the opposite direction from most
        # assertions of this kind. On a solo repo GitHub's refusal to let an
        # author approve their own pull request makes any positive count
        # unmergeable, so raising this is not a tightening but a deadlock, and
        # the pressure it creates lands on the ruleset itself.
        #
        # When a second person gets write access: raise this to 1 and change the
        # assertion here in the same commit. That is the point of pinning it —
        # the value and the reason move together, and the day the reason changes
        # is a day someone is reading this file.
        rule = _rule("pull_request") or {}
        count = rule.get("parameters", {}).get("required_approving_review_count")
        assert count == 0, (
            f"required_approving_review_count is {count!r}, not 0.\n"
            "GitHub does not let an author approve their own pull request. With "
            "one contributor, any positive count means no human pull request can "
            "ever merge — and the way out of that, under time pressure, is "
            "weakening the ruleset.\n\n"
            "If this repo now has a second person with write access, 1 is right: "
            "update this assertion and this comment together."
        )


class TestThesePinsAreNotVacuous:
    """
    Every assertion above reads through ``.get`` chains that answer ``None`` on a
    file that is missing, empty, or shaped differently than assumed. These make
    that impossible to mistake for a pass.
    """

    def test_the_ruleset_is_there_and_is_json(self):
        assert _RULESET.is_file(), f"{_RULESET} is missing"
        assert isinstance(_ruleset(), dict)

    def test_the_pull_request_rule_is_there(self):
        # `_rule` answers None for an absent rule, and the approval assertion
        # would then compare None to 0 and fail with a message about the count
        # rather than about the missing rule. The guard next door asserts the
        # rule exists for its own reasons; this says why *this* file needs it.
        assert _rule("pull_request"), (
            "The ruleset has no pull_request rule, so there is no approval count "
            "to pin and a direct push to main is accepted outright."
        )

    def test_bypass_actors_is_a_list_that_was_actually_read(self):
        # An absent `bypass_actors` key is a legitimate ruleset — it means nobody
        # may bypass — but it is not this repo's, and the tests above read it
        # through a default that would let its absence pass as "nothing to
        # check". Asserted here so the key going missing reports as the key going
        # missing.
        actors = _ruleset().get("bypass_actors")
        assert isinstance(actors, list), (
            f"`bypass_actors` is {actors!r}, not a list.\n"
            "Absent, it means nobody may bypass — a tightening, and a real edit, "
            "but not the ruleset this repo recorded. Either restore the admin "
            "bypass or update this file to say the grant is gone."
        )


_GUARD = Path(__file__).resolve().parent / "test_required_checks.py"

# The upstream commit the guard was copied from, as its own header records it.
# Pinned here as well as there so the two cannot drift apart: a re-copy has to
# touch the header, this constant, and the hash below, in one commit.
_GUARD_UPSTREAM_SHA = "ae78c6b3"

# sha256 of the guard below its header, newlines normalised to \n. Read
# TestTheCopiedGuardWasNotEdited before changing it — in particular, what it
# does and does not prove.
_GUARD_BODY_SHA256 = "fcf394ca5d7cf1a220e97123cdb2be2be5472462049984473c7966853782c4e3"


def _guard_body() -> str:
    """
    The guard from its module docstring down — the part the header promises is
    the template verbatim.

    Split on the first line that is exactly ``\"\"\"``, which is the same seam
    upstream's own ``TestTheLiveGuardMatchesTheTemplate`` uses.

    A hash is taken over the result, so newlines have to be normalised: this repo
    has files with mixed line endings, and a checkout or an editor that rewrote
    the guard's endings without touching a character of it would otherwise report
    as an edit. **``read_text`` is what actually does that** — it opens in text
    mode, so universal-newline translation has already turned CRLF into LF before
    the replace below runs, which makes that replace a no-op today. It is kept
    because it is the line that states the invariant: if the read is ever changed
    to ``read_bytes`` the normalisation must not quietly leave with it.
    """
    lines = _GUARD.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.rstrip("\r\n") == '"""')
    return "".join(lines[start:]).replace("\r\n", "\n")


class TestTheCopiedGuardWasNotEdited:
    """
    ``tests/test_required_checks.py`` is a copy of a template maintained in
    github.com/marcosfsousa/gh-repo-baseline, and its header says fixes belong
    upstream "or they are lost on the next copy". Until now nothing checked that.

    **What this proves: the copy has not been edited since the hash was
    recorded.** That is the failure that actually happens here — a session finds
    a bug in the guard, fixes it in the file it found it in, and the fix is
    reverted by the next re-copy while every repo copying the template keeps the
    bug. #76 has three such upstream-owned bugs open against this very file, so
    the temptation is live and named.

    **What it does not prove: that the copy matches upstream.** The hash is
    recorded by the same person doing the copy, so it attests local
    non-modification, not identity. Proving identity needs the template at
    ``_GUARD_UPSTREAM_SHA``, which means a network fetch — upstream's
    ``TestTheLiveGuardMatchesTheTemplate`` gets away with a plain file diff only
    because it holds both copies in one repo. That check belongs in a CI step,
    not in pytest, and is deliberately not attempted here. Do not read a green
    tick on this class as "we match the baseline".

    The hash covers this repo's two documented per-repo edits — ``_WORKFLOW``
    naming ``tests.yml`` rather than the template's ``ci.yml``, and
    ``test_step_names_are_not_collected`` asserting ``"Tests"`` rather than
    ``"CI"`` — because it hashes the local file as it stands. A third such edit
    would be indistinguishable from the drift this is here to catch, which is the
    point: it should cost a deliberate update of the constant.

    A re-copy is *meant* to break this. Diff against the upstream sha first, then
    update the header, the sha and the hash together.
    """

    def test_the_guard_body_is_unchanged(self):
        actual = hashlib.sha256(_guard_body().encode("utf-8")).hexdigest()
        assert actual == _GUARD_BODY_SHA256, (
            f"{_GUARD.name} hashes to {actual}, not the recorded "
            f"{_GUARD_BODY_SHA256}.\n\n"
            "That file is a copy and is not this repo's to edit. If you were "
            "fixing a bug in it: the fix belongs in gh-repo-baseline's "
            "templates/tests/, and comes back here as a re-copy — done locally "
            "it is lost the next time anyone copies the template, and every "
            "other repo keeps the bug.\n\n"
            "If this IS a re-copy, update the header, _GUARD_UPSTREAM_SHA and "
            "_GUARD_BODY_SHA256 in the same commit.\n\n"
            "This assertion attests that the local copy is unmodified. It does "
            "not verify it against upstream — nothing here can, without a "
            "network fetch."
        )

    def test_the_header_still_names_the_sha_the_hash_is_anchored_to(self):
        # The hash alone would go green on a re-copy whose header was updated and
        # whose constant was not, leaving the recorded provenance pointing at a
        # commit the bytes no longer came from. Cheap, and it makes the two
        # records fail together rather than one covering for the other.
        header = _GUARD.read_text(encoding="utf-8").split('"""')[0]
        assert _GUARD_UPSTREAM_SHA in header, (
            f"{_GUARD.name}'s header does not name {_GUARD_UPSTREAM_SHA}, which "
            "is the commit this file's hash is recorded against.\n"
            "Either the guard was re-copied without updating _GUARD_UPSTREAM_SHA "
            "and _GUARD_BODY_SHA256 here, or the header lost the sha that gives "
            "the next copy something to diff against."
        )

    def test_the_hash_is_taken_over_a_body_and_not_the_whole_file(self):
        # Guards the guard, as upstream's `test_only_the_header_differs` does for
        # the same seam.
        #
        # The seam is *slippery*, which is the thing to understand here. It is the
        # first line equal to `\"\"\"`, and the guard contains several — so deleting
        # the module docstring's opening quote does not raise: `next()` simply
        # finds the *closing* one and the body silently starts 70-odd lines lower.
        # Measured, not reasoned about: with that one line removed, two of this
        # class's three tests still pass. Only `test_the_guard_body_is_unchanged`
        # notices, and only because the hash moved.
        #
        # (An earlier version of this comment claimed the vanishing case raises
        # StopIteration and errors every test in the class. It does not, and could
        # only do so in a file with no other bare `\"\"\"` line at all.)
        #
        # So the header assertion below is the one that makes this test earn its
        # name: the guard's header is entirely `#` comments, and every way the seam
        # can slip *downwards* drags docstring prose into the header. Checking the
        # header's shape catches that class outright, rather than hoping the hash
        # happens to move.
        whole = _GUARD.read_text(encoding="utf-8").replace("\r\n", "\n")
        body = _guard_body()
        header = whole[: len(whole) - len(body)]
        assert body.startswith('"""'), (
            "the guard's body does not start at its module docstring — the seam "
            "`_guard_body` splits on has moved"
        )
        assert all(line.startswith("#") for line in header.splitlines() if line.strip()), (
            "the guard's header contains a non-comment line, so `_guard_body` split "
            "somewhere below the module docstring rather than at it.\n"
            "The hash is then taken over less of the file than it claims, and the "
            "part left out is the provenance comment a re-copy is supposed to "
            "rewrite. Most likely the module docstring's opening `\"\"\"` was "
            "removed or moved, and the split landed on a later one."
        )
        assert len(body) < len(whole), (
            "the guard's header is empty, so the hash covers the whole file "
            "including the provenance comment a re-copy rewrites"
        )
        assert "gh-repo-baseline" in header, (
            "the guard's header no longer says where the file is copied from, "
            "which is the claim this whole class exists to hold someone to"
        )

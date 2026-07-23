from __future__ import annotations

import logging
from typing import Any, Protocol, cast

import numpy as np
from sentence_transformers import SentenceTransformer

from jobscout.models import JobListing, UserProfile

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "intfloat/multilingual-e5-small"

# e5 expresses the query/document asymmetry through text prefixes, not through a
# separate task flag. Without them the model silently underperforms — the single
# highest-risk item in this stage, whose only failure mode is quiet degradation
# (docs/research/embedding-model-german-corpus.md; N #19 §5). Applied per call site,
# never uniformly, because the same encode path serves both roles (O #21).
_QUERY_PREFIX = "query: "
_PASSAGE_PREFIX = "passage: "

# Set explicitly rather than inherited. e5-small defaults to 512, so this changes no
# behaviour today — which is exactly why it must be written: N #19 §5 measured a
# different model shipping a 128-token default that truncated 99% of documents *and*
# the query without anyone noticing. The assertion exists so the next swap cannot
# repeat it.
_MAX_SEQ_LENGTH = 512


class _Encoder(Protocol):
    """The slice of SentenceTransformer this module depends on.

    Production passes a real ``SentenceTransformer``; tests pass a recording stub so
    the prefixed strings — the only observable proof the prefixes were applied — can
    be asserted. Typed loosely so the concrete ``SentenceTransformer`` (overloaded
    ``encode``, ``int | None`` window) assigns to it without ceremony.
    """

    max_seq_length: int | None

    def encode(self, sentences: Any, **kwargs: Any) -> Any: ...


def _build_profile_text(profile: UserProfile) -> str:
    """Compose the ranking query from the profile's discriminative fields.

    ``ideal_role`` and ``background`` carry the most distinctive text in the profile
    and were previously ignored by the embedder (F #9 decision 1). ``skills.learning``
    stays out — it describes what the candidate cannot yet do. English-only: N #19 §5
    amended F's bilingual query away, and no contract vocabulary is added because the
    pool is ~100% ``contracting`` and such terms discriminate nothing.
    """
    parts = [
        "Target roles: " + ", ".join(profile.target_roles),
        "Strong skills: " + ", ".join(profile.skills.strong),
        "Working knowledge: " + ", ".join(profile.skills.working_knowledge),
    ]
    if profile.ideal_role:
        parts.append("Ideal role: " + profile.ideal_role.strip())
    if profile.background:
        parts.append("Background: " + profile.background.strip())
    return ". ".join(parts)


def _build_job_text(job: JobListing) -> str:
    return f"{job.title}. {job.description}"


class ProfileEmbedder:
    """Encodes a UserProfile and JobListings into L2-normalised vectors.

    The model is loaded eagerly at construction time. The profile embedding
    is cached after the first call to ``encode_profile``.
    """

    def __init__(
        self,
        model_name: str = _DEFAULT_MODEL,
        encoder: _Encoder | None = None,
    ) -> None:
        if encoder is None:
            logger.info("Loading sentence-transformer model '%s'", model_name)
            # cast: SentenceTransformer satisfies _Encoder at runtime, but its
            # max_seq_length is a property, which pyright will not match to a mutable
            # protocol attribute.
            encoder = cast(_Encoder, SentenceTransformer(model_name))
        self._model: _Encoder = encoder
        self._model.max_seq_length = _MAX_SEQ_LENGTH
        self._profile_vec: np.ndarray | None = None
        self._cached_profile_text: str | None = None

    def encode_profile(self, profile: UserProfile) -> np.ndarray:
        """Return the L2-normalised profile embedding, cached after first call.

        The cache key is the prefixed text, so it never mixes prefixed and unprefixed
        forms and cannot re-encode on every call.
        """
        text = _QUERY_PREFIX + _build_profile_text(profile)
        if self._profile_vec is None or text != self._cached_profile_text:
            self._profile_vec = self._encode([text])[0]
            self._cached_profile_text = text
        vec = self._profile_vec
        assert vec is not None  # just assigned above if it was None
        return vec

    def encode_jobs(self, jobs: list[JobListing]) -> np.ndarray:
        """Return an (n, dim) matrix of L2-normalised job embeddings.

        Job documents are passages, so they take the ``passage:`` prefix.
        """
        return self._encode([_PASSAGE_PREFIX + _build_job_text(j) for j in jobs])

    def encode_feedback(self, docs: list[str]) -> np.ndarray:
        """Return an (k, dim) matrix for feedback-centroid documents.

        These take the ``query:`` prefix — a deliberate deviation from e5's guidance,
        which calls document-vs-document a symmetric task prescribing ``query:`` on
        both sides. By origin these are passages (``db.py`` composes them exactly like
        ``_build_job_text``), but by function the centroid occupies the profile query's
        slot, and the tiebreaker is the blend, not the taxonomy: ``feedback_weight``
        is only meaningful if its two terms share a scale, and under ``query:`` both
        the profile term and the centroid term are query-vs-passage. Encoding the pool
        twice to honour both was rejected (O #21) — it doubles the pool encode on every
        CPU run of a daily Action to fix a recall-only signal.
        """
        return self._encode([_QUERY_PREFIX + d for d in docs])

    def _encode(self, texts: list[str]) -> np.ndarray:
        """Encode raw (already-prefixed) strings into L2-normalised vectors.

        ``np.asarray`` pins the return to ndarray — SentenceTransformer.encode is typed
        to also return a Tensor, which it does not under these kwargs.
        """
        return np.asarray(self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False))

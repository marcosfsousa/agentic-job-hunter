"""Tests for ranking/embedder.py and ranking/scorer.py.

Verifies that an ML-focused job ranks above a generic Software Engineer job
when scored against an ML-focused profile. No network calls — model loads
from local cache via a module-scoped fixture.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from jobscout.models import (
    DealbreakersConfig,
    JobListing,
    LocationConfig,
    RateConfig,
    SkillsConfig,
    UserProfile,
)
from jobscout.ranking.embedder import ProfileEmbedder
from jobscout.ranking.scorer import rank_jobs


# ---------------------------------------------------------------------------
# Recording encoder — the seam that makes the query:/passage: prefixes assertable.
#
# The prefixes are the single highest-risk item in the e5 swap: their only failure
# mode is silent underperformance (N #19). Production passes nothing and loads a real
# SentenceTransformer; this stub records every string handed to the model so the three
# prefixed paths — profile (query:), jobs (passage:), feedback centroid (query:) — can
# be pinned. It deliberately ships a wrong max_seq_length so the constructor's explicit
# 512 is observable.
# ---------------------------------------------------------------------------

class RecordingEncoder:
    def __init__(self, dim: int = 8) -> None:
        self.dim = dim
        self.max_seq_length = 128   # wrong on purpose; ProfileEmbedder must override to 512
        self.calls: list[list[str]] = []

    def encode(
        self, texts: list[str], normalize_embeddings: bool = True, show_progress_bar: bool = False
    ) -> np.ndarray:
        self.calls.append(list(texts))
        vecs = np.array([self._vec(t) for t in texts], dtype=float)
        if normalize_embeddings:
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            vecs = vecs / np.where(norms == 0.0, 1.0, norms)
        return vecs

    def _vec(self, text: str) -> np.ndarray:
        v = np.ones(self.dim)
        for i, ch in enumerate(text):
            v[i % self.dim] += ord(ch) % 17
        return v

    @property
    def texts(self) -> list[str]:
        return [t for call in self.calls for t in call]


# ---------------------------------------------------------------------------
# Module-level job fixtures
# ---------------------------------------------------------------------------

def _make_job(id: str, title: str, description: str) -> JobListing:
    return JobListing(
        id=id,
        source="test",
        title=title,
        company="Test GmbH",
        description=description,
        location="Berlin, Germany",
        remote_percentage=50,
        url=f"https://example.com/job/{id}",
        posted_date=datetime(2026, 3, 19, 9, 30, 0),
        fetched_at=datetime(2026, 3, 19, 12, 0, 0),
        raw_data={},
    )


ML_JOB = _make_job(
    id="ml-1",
    title="ML Engineer",
    description=(
        "Build and deploy machine learning models at scale. "
        "Experience with PyTorch, HuggingFace Transformers, and LLM fine-tuning required. "
        "Work on RAG pipelines, vector databases, and LLM application development. "
        "Familiarity with MLOps tooling and model serving a strong plus."
    ),
)

SWE_JOB = _make_job(
    id="swe-1",
    title="Software Engineer",
    description=(
        "Design and build scalable backend services and REST APIs. "
        "Strong experience with Java or Go, microservices architecture, and CI/CD pipelines. "
        "Work closely with product teams on system design and code reviews. "
        "Experience with Docker, Kubernetes, and cloud infrastructure preferred."
    ),
)

# A German ML project. The whole point of the multilingual e5 swap: this must outrank
# an English backend job for an English ML profile. It cannot under the English-only
# multi-qa-MiniLM model, which scores a German document near-unrelated to its own
# meaning (N #19).
GERMAN_ML_JOB = _make_job(
    id="de-ml-1",
    title="Machine Learning Engineer",
    description=(
        "Wir suchen einen erfahrenen Machine Learning Engineer für den Aufbau und die "
        "Bereitstellung von LLM-Anwendungen und RAG-Pipelines. Erfahrung mit HuggingFace "
        "Transformers, Vektordatenbanken und der Entwicklung von KI-Anwendungen ist "
        "erforderlich. Sie entwickeln NLP-Systeme und agentische Anwendungen vom Prototyp "
        "bis zur Produktion."
    ),
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def embedder() -> ProfileEmbedder:
    return ProfileEmbedder()


@pytest.fixture(scope="module")
def ml_profile() -> UserProfile:
    return UserProfile(
        name="Marcos",
        background="3 months hands-on AI engineering: built RAG pipelines and NLP systems.",
        ideal_role="Building and deploying LLM-based applications, RAG pipelines, or NLP systems.",
        target_roles=["ML Engineer", "AI Engineer"],
        skills=SkillsConfig(
            strong=[
                "RAG systems",
                "LangChain",
                "LLM application development",
                "Sentence Transformers",
                "HuggingFace ecosystem",
            ],
            working_knowledge=["Python", "PyTorch", "Docker", "REST APIs"],
            learning=["MLflow", "AWS SageMaker"],
        ),
        location=LocationConfig(target_countries=["Germany"]),
        rate=RateConfig(),
        dealbreakers=DealbreakersConfig(),
        freelancermap_queries=["Machine Learning"],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRankJobs:
    def test_ml_job_ranks_above_swe_job(self, embedder, ml_profile):
        results = rank_jobs([ML_JOB, SWE_JOB], ml_profile, embedder)
        assert results[0].listing.id == "ml-1", (
            f"ML job should rank first for an ML profile, got '{results[0].listing.id}' "
            f"(scores: ml={results[0].embedding_score:.4f} not first)"
        )

    def test_results_are_sorted_descending(self, embedder, ml_profile):
        results = rank_jobs([ML_JOB, SWE_JOB], ml_profile, embedder)
        scores = [r.embedding_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_scores_are_valid_cosine_similarity(self, embedder, ml_profile):
        results = rank_jobs([ML_JOB, SWE_JOB], ml_profile, embedder)
        for r in results:
            assert -1.0 <= r.embedding_score <= 1.0

    def test_empty_input_returns_empty(self, embedder, ml_profile):
        assert rank_jobs([], ml_profile, embedder) == []

    def test_single_job_returns_one_result(self, embedder, ml_profile):
        results = rank_jobs([ML_JOB], ml_profile, embedder)
        assert len(results) == 1
        assert results[0].listing.id == "ml-1"

    def test_no_feedback_docs_same_as_baseline(self, embedder, ml_profile):
        baseline = rank_jobs([ML_JOB, SWE_JOB], ml_profile, embedder)
        with_empty = rank_jobs([ML_JOB, SWE_JOB], ml_profile, embedder, feedback_docs=[])
        with_none = rank_jobs([ML_JOB, SWE_JOB], ml_profile, embedder, feedback_docs=None)
        assert [r.listing.id for r in baseline] == [r.listing.id for r in with_empty]
        assert [r.listing.id for r in baseline] == [r.listing.id for r in with_none]

    def test_feedback_centroid_boosts_similar_job(self, embedder, ml_profile):
        # Feedback doc is ML-focused — should widen the gap between ML and SWE jobs
        feedback_docs = [
            "Senior ML Engineer. Deep learning, PyTorch, model deployment, LLM fine-tuning."
        ]
        baseline = rank_jobs([ML_JOB, SWE_JOB], ml_profile, embedder)
        boosted = rank_jobs([ML_JOB, SWE_JOB], ml_profile, embedder, feedback_docs=feedback_docs)

        baseline_gap = baseline[0].embedding_score - baseline[1].embedding_score
        boosted_gap = boosted[0].embedding_score - boosted[1].embedding_score

        # ML job should still rank first, and the gap should increase
        assert boosted[0].listing.id == "ml-1"
        assert boosted_gap > baseline_gap

    def test_german_ml_ranks_above_english_backend(self, embedder, ml_profile):
        """The reason for the multilingual swap: a German ML project must outrank an
        English backend job for an English ML profile. Fails under the old English-only
        model, which is why this is the assertion that guards the swap end to end."""
        results = rank_jobs([GERMAN_ML_JOB, SWE_JOB], ml_profile, embedder)
        assert results[0].listing.id == "de-ml-1", (
            f"German ML job should rank first, got '{results[0].listing.id}' "
            f"(de-ml={results[0].embedding_score:.4f})"
        )


class TestEmbedderPrefixesAndWiring:
    """The prefixes are the highest-risk item in the swap and fail silently. These pin
    them through the recording encoder — the only place the prefixed strings are
    observable — using O (#21)'s decided wiring: prefix per call site, not uniformly."""

    def test_profile_query_is_query_prefixed(self, ml_profile):
        enc = RecordingEncoder()
        ProfileEmbedder(encoder=enc).encode_profile(ml_profile)
        profile_texts = [t for t in enc.texts if "Target roles" in t]
        assert len(profile_texts) == 1
        assert profile_texts[0].startswith("query: ")

    def test_jobs_are_passage_prefixed(self, ml_profile):
        enc = RecordingEncoder()
        ProfileEmbedder(encoder=enc).encode_jobs([ML_JOB, SWE_JOB])
        passages = [t for t in enc.texts if t.startswith("passage: ")]
        assert len(passages) == 2

    def test_feedback_centroid_is_query_prefixed_not_passage(self, ml_profile):
        """The counter-intuitive one, asserted by name: the centroid takes `query:`, a
        deliberate deviation from e5's symmetric-task guidance (O #21). A future reader
        "correcting" it to `passage:` would break this and nothing else."""
        enc = RecordingEncoder()
        embedder = ProfileEmbedder(encoder=enc)
        rank_jobs([ML_JOB, SWE_JOB], ml_profile, embedder, feedback_docs=["Past ML job."])
        fb_texts = [t for t in enc.texts if "Past ML job." in t]
        assert len(fb_texts) == 1
        assert fb_texts[0].startswith("query: ")
        assert not fb_texts[0].startswith("passage: ")

    def test_jobs_encoded_once_even_with_feedback(self, ml_profile):
        """Pins O (#21)'s rejection of the encode-twice design: exactly one encode call
        carries the passages, containing each job once, even when feedback is supplied."""
        enc = RecordingEncoder()
        embedder = ProfileEmbedder(encoder=enc)
        rank_jobs([ML_JOB, SWE_JOB], ml_profile, embedder, feedback_docs=["ML feedback doc."])
        passage_calls = [c for c in enc.calls if any(t.startswith("passage: ") for t in c)]
        assert len(passage_calls) == 1
        assert len(passage_calls[0]) == 2

    def test_max_seq_length_set_explicitly_to_512(self, ml_profile):
        """Overrides the encoder's shipped default (128 here) — guards the 99%-truncation
        trap N #19 §5 measured on a model with a wrong default."""
        enc = RecordingEncoder()
        embedder = ProfileEmbedder(encoder=enc)
        assert embedder._model.max_seq_length == 512

    def test_query_folds_in_ideal_role_and_background_but_not_learning(self):
        """ideal_role and background — the most discriminative profile text — are folded
        in; skills.learning stays out (it describes what the candidate cannot yet do)."""
        enc = RecordingEncoder()
        profile = UserProfile(
            name="Marcos",
            background="UNIQUEBACKGROUNDTOKEN application-layer builder.",
            ideal_role="UNIQUEIDEALTOKEN ship LLM apps end to end.",
            target_roles=["ML Engineer"],
            skills=SkillsConfig(
                strong=["RAG systems"],
                working_knowledge=["Python"],
                learning=["UNIQUELEARNINGTOKEN"],
            ),
            location=LocationConfig(target_countries=["Germany"]),
            rate=RateConfig(),
            dealbreakers=DealbreakersConfig(),
            freelancermap_queries=["Machine Learning"],
        )
        ProfileEmbedder(encoder=enc).encode_profile(profile)
        query = enc.texts[0]
        assert "UNIQUEBACKGROUNDTOKEN" in query
        assert "UNIQUEIDEALTOKEN" in query
        assert "UNIQUELEARNINGTOKEN" not in query


class TestMaxSeqLengthOnRealModel:
    def test_real_model_max_seq_length_is_512(self, embedder):
        """One cheap assertion against the real e5 model in the shared fixture."""
        assert embedder._model.max_seq_length == 512

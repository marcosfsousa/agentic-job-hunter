from __future__ import annotations

import logging

import numpy as np
from sentence_transformers import SentenceTransformer

from jobscout.models import JobListing, UserProfile

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "multi-qa-MiniLM-L6-cos-v1"


def _build_profile_text(profile: UserProfile) -> str:
    parts = [
        "Target roles: " + ", ".join(profile.target_roles),
        "Strong skills: " + ", ".join(profile.skills.strong),
        "Working knowledge: " + ", ".join(profile.skills.working_knowledge),
    ]
    return ". ".join(parts)


def _build_job_text(job: JobListing) -> str:
    return f"{job.title}. {job.description}"


class ProfileEmbedder:
    """Encodes a UserProfile and JobListings into L2-normalised vectors.

    The model is loaded eagerly at construction time. The profile embedding
    is cached after the first call to ``encode_profile``.
    """

    def __init__(self, model_name: str = _DEFAULT_MODEL) -> None:
        logger.info("Loading sentence-transformer model '%s'", model_name)
        self._model = SentenceTransformer(model_name)
        self._profile_vec: np.ndarray | None = None
        self._cached_profile_text: str | None = None

    def encode_profile(self, profile: UserProfile) -> np.ndarray:
        """Return the L2-normalised profile embedding, cached after first call."""
        text = _build_profile_text(profile)
        if self._profile_vec is None or text != self._cached_profile_text:
            self._profile_vec = self._model.encode(text, normalize_embeddings=True)
            self._cached_profile_text = text
        return self._profile_vec

    def encode_jobs(self, jobs: list[JobListing]) -> np.ndarray:
        """Return an (n, dim) matrix of L2-normalised job embeddings."""
        return self.encode_texts([_build_job_text(j) for j in jobs])

    def encode_texts(self, texts: list[str]) -> np.ndarray:
        """Return an (n, dim) matrix of L2-normalised embeddings for raw text strings."""
        return self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

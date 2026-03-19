from __future__ import annotations

import numpy as np

from jobscout.models import JobListing, ScoredJob, UserProfile
from jobscout.ranking.embedder import ProfileEmbedder


def rank_jobs(
    jobs: list[JobListing],
    profile: UserProfile,
    embedder: ProfileEmbedder,
) -> list[ScoredJob]:
    """Embed profile + jobs, compute cosine similarity, return sorted ScoredJob list.

    Vectors are L2-normalised by the embedder, so dot product == cosine similarity.

    Args:
        jobs: Job listings to rank.
        profile: User profile to rank against.
        embedder: Pre-loaded ProfileEmbedder instance.

    Returns:
        Jobs sorted by embedding_score descending.
    """
    if not jobs:
        return []

    profile_vec: np.ndarray = embedder.encode_profile(profile)  # (dim,)
    job_vecs: np.ndarray = embedder.encode_jobs(jobs)           # (n, dim)

    scores: np.ndarray = job_vecs @ profile_vec                 # (n,)

    scored = [
        ScoredJob(listing=job, embedding_score=float(score))
        for job, score in zip(jobs, scores)
    ]

    return sorted(scored, key=lambda s: s.embedding_score, reverse=True)

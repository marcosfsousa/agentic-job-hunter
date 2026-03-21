from __future__ import annotations

import numpy as np

from jobscout.models import JobListing, ScoredJob, UserProfile
from jobscout.ranking.embedder import ProfileEmbedder


def rank_jobs(
    jobs: list[JobListing],
    profile: UserProfile,
    embedder: ProfileEmbedder,
    feedback_docs: list[str] | None = None,
    feedback_weight: float = 0.2,
) -> list[ScoredJob]:
    """Embed profile + jobs, compute cosine similarity, return sorted ScoredJob list.

    Vectors are L2-normalised by the embedder, so dot product == cosine similarity.
    When feedback_docs are provided, blends a centroid of past-interested job embeddings
    into the score: final = (1 - feedback_weight) * profile_score + feedback_weight * centroid_score.

    Args:
        jobs: Job listings to rank.
        profile: User profile to rank against.
        embedder: Pre-loaded ProfileEmbedder instance.
        feedback_docs: Raw text of past 'interested' jobs to form the feedback centroid.
        feedback_weight: Blend weight for the feedback centroid (0.0–1.0).

    Returns:
        Jobs sorted by embedding_score descending.
    """
    if not jobs:
        return []

    profile_vec: np.ndarray = embedder.encode_profile(profile)  # (dim,)
    job_vecs: np.ndarray = embedder.encode_jobs(jobs)           # (n, dim)

    scores: np.ndarray = job_vecs @ profile_vec                 # (n,)

    if feedback_docs:
        fb_vecs: np.ndarray = embedder.encode_texts(feedback_docs)  # (k, dim)
        centroid: np.ndarray = fb_vecs.mean(axis=0)
        centroid /= np.linalg.norm(centroid)
        fb_scores: np.ndarray = job_vecs @ centroid                 # (n,)
        scores = (1 - feedback_weight) * scores + feedback_weight * fb_scores

    scored = [
        ScoredJob(listing=job, embedding_score=float(score))
        for job, score in zip(jobs, scores)
    ]

    return sorted(scored, key=lambda s: s.embedding_score, reverse=True)

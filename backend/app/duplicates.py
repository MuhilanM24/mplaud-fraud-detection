"""Duplicate-work detection: NLP semantic similarity + geospatial clustering.

NLP backend (in order of preference, controlled by MPLAUD_NLP_BACKEND):
  1. sentence-transformers (all-MiniLM-L6-v2) — real sentence embeddings, used
     automatically when the model is cached/available (e.g. baked into Docker).
  2. Offline fallback: TF-IDF over word 1-2 grams + character 3-5 grams with
     cosine similarity — a classical semantic-similarity proxy that requires
     no network and runs anywhere. The active backend is always reported to
     the UI (/api/meta) so nothing is overclaimed.

Geospatial layer: DBSCAN with haversine metric (eps = 1.5 km) finds clusters;
pairs within a cluster whose descriptions are near-duplicates are flagged.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from . import config


class NLPBackend:
    def __init__(self, preference: str = "auto"):
        self.preference = preference
        self.backend = "tfidf"
        self.label = ("TF-IDF (word 1-2 gram + char 3-5 gram) cosine similarity "
                      "— offline fallback backend")
        self.model = None
        self._load()

    def _load(self) -> None:
        if self.preference == "tfidf":
            return
        import os
        # In auto mode fail fast: if the model is not already cached, skip
        # network retries entirely (offline-friendly) and use the fallback.
        if self.preference == "auto":
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            self.model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
            self.backend = "sbert"
            self.label = ("sentence-transformers all-MiniLM-L6-v2 sentence "
                          "embeddings + cosine similarity")
        except Exception:  # no network / package missing -> documented fallback
            if self.preference == "sbert":
                raise
            self.backend = "tfidf"

    @property
    def sim_threshold(self) -> float:
        return (config.DUP_SIM_THRESHOLD_SBERT if self.backend == "sbert"
                else config.DUP_SIM_THRESHOLD_TFIDF)

    def encode(self, texts: list[str]):
        if self.backend == "sbert":
            return self.model.encode(texts, normalize_embeddings=True,
                                     show_progress_bar=False)
        word = TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True)
        char = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)
        Xw = word.fit_transform(texts)
        Xc = char.fit_transform(texts)
        return (Xw, Xc)

    @staticmethod
    def _token_set_ratio(a: str, b: str) -> float:
        """Difflib ratio over the SET of significant tokens — robust to word
        order, filler words ('at', 'in', 'of') and small edits."""
        import difflib
        stop = {"at", "in", "of", "the", "and", "to", "from", "for", "with",
                "along", "a", "an", "near", "village", "area", "road"}
        ta = sorted({t for t in a.lower().replace(",", " ").split() if t not in stop})
        tb = sorted({t for t in b.lower().replace(",", " ").split() if t not in stop})
        return difflib.SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()

    def similarity_matrix(self, texts: list[str]) -> np.ndarray:
        if len(texts) < 2:
            return np.zeros((len(texts), len(texts)))
        if self.backend == "sbert":
            emb = self.encode(texts)
            return cosine_similarity(emb)
        Xw, Xc = self.encode(texts)
        cos = 0.5 * np.maximum(cosine_similarity(Xw), cosine_similarity(Xc)) + \
            0.5 * (cosine_similarity(Xw) + cosine_similarity(Xc)) / 2
        # blend with token-set ratio (catches paraphrases that char n-grams miss)
        n = len(texts)
        tsr = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                v = self._token_set_ratio(texts[i], texts[j])
                tsr[i, j] = tsr[j, i] = v
        return 0.5 * cos + 0.5 * tsr


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def detect_duplicates(df: pd.DataFrame, nlp: NLPBackend | None = None) -> dict:
    """Returns {pairs: [...], nearby_counts: {project_id: n}, backend_label}."""
    nlp = nlp or NLPBackend(config.NLP_BACKEND)
    result = {"pairs": [], "nearby_counts": {}, "backend": nlp.backend,
              "backend_label": nlp.label,
              "sim_threshold": nlp.sim_threshold,
              "distance_km": config.DUP_DISTANCE_KM}
    has_text = "work_description" in df.columns and df["work_description"].notna().any()
    has_geo = ("geo_lat" in df.columns and "geo_lon" in df.columns
               and df[["geo_lat", "geo_lon"]].notna().all().all())
    if not has_geo or not has_text or len(df) < 2:
        return result

    texts = df["work_description"].fillna("").astype(str).tolist()
    sims = nlp.similarity_matrix(texts)

    # DBSCAN over radians of coordinates -> clusters within ~1.5 km
    coords = np.radians(df[["geo_lat", "geo_lon"]].astype(float).values)
    db = DBSCAN(eps=config.DUP_DISTANCE_KM / 6371.0,
                min_samples=config.DUP_DBSCAN_MIN_SAMPLES, metric="haversine")
    labels = db.fit_predict(coords)

    # cluster membership: project_ids per cluster (size >= 2)
    clusters: dict[int, list[int]] = {}
    for i, lab in enumerate(labels):
        if lab >= 0:
            clusters.setdefault(int(lab), []).append(i)

    # nearby similar-work counts (feature for anomaly model)
    counts = {pid: 0 for pid in df["project_id"]}
    pairs = []
    for members in clusters.values():
        if len(members) < 2:
            continue
        for a_i in range(len(members)):
            for b_i in range(a_i + 1, len(members)):
                i, j = members[a_i], members[b_i]
                sim = float(sims[i, j])
                dist_km = _haversine_km(df["geo_lat"].iloc[i], df["geo_lon"].iloc[i],
                                        df["geo_lat"].iloc[j], df["geo_lon"].iloc[j])
                if sim >= 0.55:  # loosely similar works nearby count for the feature
                    counts[df["project_id"].iloc[i]] = counts.get(df["project_id"].iloc[i], 0) + 1
                    counts[df["project_id"].iloc[j]] = counts.get(df["project_id"].iloc[j], 0) + 1
                if sim >= nlp.sim_threshold and dist_km <= config.DUP_DISTANCE_KM:
                    pairs.append({
                        "project_id_a": df["project_id"].iloc[i],
                        "project_id_b": df["project_id"].iloc[j],
                        "description_a": texts[i][:140],
                        "description_b": texts[j][:140],
                        "similarity": round(sim, 3),
                        "distance_km": round(dist_km, 3),
                        "district": df["district"].iloc[i] if "district" in df else None,
                        "mp_a": df["mp_name"].iloc[i] if "mp_name" in df else None,
                        "mp_b": df["mp_name"].iloc[j] if "mp_name" in df else None,
                    })
    pairs.sort(key=lambda p: p["similarity"], reverse=True)
    result["pairs"] = pairs
    result["nearby_counts"] = counts
    return result


def duplicate_component(dup_result: dict, project_id: str) -> float:
    """0-100 contribution from duplicate involvement for one project."""
    best = 0.0
    for p in dup_result.get("pairs", []):
        if project_id in (p["project_id_a"], p["project_id_b"]):
            # similarity 1.0 at distance 0 -> ~90 points
            prox = max(0.0, 1.0 - p["distance_km"] / config.DUP_DISTANCE_KM)
            best = max(best, min(90.0, 90.0 * (0.5 + 0.5 * p["similarity"]) * (0.6 + 0.4 * prox)))
    return best

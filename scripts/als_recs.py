# scripts/als_recs.py
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path
from scipy.sparse import csr_matrix
from implicit.als import AlternatingLeastSquares

from scripts.config import RunConfig
from scripts.io_utils import write_parquet_batches


def fit_als(events_train: pd.DataFrame, config: RunConfig) -> tuple[AlternatingLeastSquares, csr_matrix, np.ndarray, np.ndarray]:
    print(f"grouping {len(events_train):,} events...")
    plays = events_train.groupby(["user_id", "track_id"], sort=False).size()
    
    print("factorizing...")
    user_idx, users = pd.factorize(plays.index.get_level_values(0), sort=False)
    item_idx, tracks = pd.factorize(plays.index.get_level_values(1), sort=False)
    
    print(f"building matrix {len(users):,} x {len(tracks):,}...")
    matrix = csr_matrix(
        (plays.to_numpy(np.float32) * config.als.alpha, (user_idx, item_idx)),
        shape=(len(users), len(tracks)),
        dtype=np.float32,
    )
    
    print(f"fitting ALS (factors={config.als.factors}, iter={config.als.iterations})...")
    model = AlternatingLeastSquares(
        factors=config.als.factors,
        regularization=config.als.regularization,
        iterations=config.als.iterations,
        random_state=config.seed,
    )
    model.fit(matrix.T)
    
    print("done")
    return model, matrix, users, tracks


def write_personal_als(model: AlternatingLeastSquares, matrix: csr_matrix, users: np.ndarray, tracks: np.ndarray, config: RunConfig, batch_size: int = 10_000) -> Path:
    ranks = np.arange(1, config.k + 1, dtype=np.int16)
    
    def gen():
        print(f"generating recommendations for {matrix.shape[0]:,} users...")
        for start in range(0, matrix.shape[0], batch_size):
            end = min(start + batch_size, matrix.shape[0])
            print(f"  batch {start:,}-{end:,}")
            
            ids, scores = model.recommend(
                userid=np.arange(start, end, dtype=np.int32),
                user_items=matrix[start:end],
                N=config.k,
                filter_already_liked_items=True,
            )
            
            yield pd.DataFrame({
                "user_id": np.repeat(users[start:end], config.k),
                "track_id": tracks[ids.ravel()],
                "rank": np.tile(ranks, end - start),
                "score": scores.ravel(),
            })
    
    return write_parquet_batches(config.paths.artifacts_dir / "personal_als.parquet", gen)


def write_similar_items(model: AlternatingLeastSquares, tracks: np.ndarray, config: RunConfig, batch_size: int = 10_000) -> Path:
    ranks = np.arange(1, config.k + 1, dtype=np.int16)
    
    def gen():
        print(f"generating similar items for {len(tracks):,} tracks...")
        for start in range(0, len(tracks), batch_size):
            end = min(start + batch_size, len(tracks))
            print(f"  batch {start:,}-{end:,}")
            
            ids, scores = model.similar_items(
                itemid=np.arange(start, end, dtype=np.int32),
                N=config.k + 1,
            )
            
            yield pd.DataFrame({
                "track_id": np.repeat(tracks[start:end], config.k),
                "similar_track_id": tracks[ids[:, 1:config.k + 1].ravel()],
                "rank": np.tile(ranks, end - start),
                "score": scores[:, 1:config.k + 1].ravel(),
            })
    
    return write_parquet_batches(config.paths.artifacts_dir / "similar.parquet", gen)
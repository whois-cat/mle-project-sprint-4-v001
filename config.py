from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd
import logging


@dataclass(frozen=True)
class Config:
    DATA_DIR: Path = Path("data")
    ARTIFACTS_DIR: Path = Path("artifacts")

    RAW_FILES = {
        "tracks": DATA_DIR / "tracks.parquet",
        "catalog_names": DATA_DIR / "catalog_names.parquet",
        "events": DATA_DIR / "interactions.parquet",
    }

    CLEAN_FILES = {
        "items": DATA_DIR / "items.parquet",
        "events": DATA_DIR / "events.parquet",
        "catalog_names": DATA_DIR / "catalog_names.parquet",
    }

    RECS_FILES = {
        "top_popular": ARTIFACTS_DIR / "top_popular.parquet",
        "personal_als": ARTIFACTS_DIR / "personal_als.parquet",
        "personal_als_features": ARTIFACTS_DIR / "personal_als_features.parquet",
        "similar": ARTIFACTS_DIR / "similar.parquet",
        "ranked": ARTIFACTS_DIR / "recommendations.parquet",
    }

    SERVICE_FILES = {
        "warmed_users": ARTIFACTS_DIR / "warmed_users.json",
        "model_metrics": ARTIFACTS_DIR / "model_metrics.json",
    }

    S3_DATA_PREFIX: str = "recsys/data"
    S3_RECS_PREFIX: str = "recsys/recommendations"

    EDA_PERCENTILES: tuple = (0.5, 0.9, 0.99)
    EDA_BINS: int = 80

    SEED: int = 42

    SPLIT_DATE: pd.Timestamp = pd.Timestamp("2022-12-16")
    WINDOW_DAYS: int = 30

    CV_FOLDS: int = 3
    CV_STEP_DAYS: int = 30
    CV_VAL_DAYS: int = 14
    CV_USERS: int = 12_000
    CV_ALS_BATCH_USERS: int = 6_000

    PARQUET_BATCH_ROWS: int = 200_000
    FEATURE_BATCH_ROWS: int = 300_000

    K_CANDIDATES: int = 100
    TOP_K: int = 10

    ALS_FACTORS: int = 64
    ALS_ITERATIONS: int = 30
    ALS_REGULARIZATION: float = 0.01
    ALS_ALPHA: float = 40.0
    ALS_BATCH_USERS: int = 20_000
    ALS_SUBBATCH_USERS: int = 2000

    SIMILAR_TOP_N: int = 10_000
    SIMILAR_BATCH: int = 128

    RANKER_VAL_DAYS: int = 14
    RANKER_USERS: int = 50_000

    BATCH_ROWS: int = 200_000
    TRAIN_USERS: int = 80_000
    TRAIN_ROWS_LIMIT: int = 1_200_000

    LGBM_PARAMS = {
        "objective": "lambdarank",
        "metric": "ndcg",
        "learning_rate": 0.05,
        "num_leaves": 63,
        "verbosity": -1,
        "seed": SEED,
    }

    ONLINE_TAKE: int = 3
    ONLINE_KEEP: int = 200
    ONLINE_HISTORY_TAKE: int = 10

    SIMILAR_PER_TRACK: int = 30 
    CACHE_TTL_SECONDS: int = 3600

    LOG_LEVEL: int = logging.INFO


CFG = Config()
RNG = np.random.default_rng(CFG.SEED)

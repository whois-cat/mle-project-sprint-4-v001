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
        "items": "items.parquet",
        "events": "events.parquet",
        "catalog_names": "catalog_names.parquet",
    }

    RECS_FILES = {
        "top_popular": "top_popular.parquet",
        "personal_als": "personal_als.parquet",
        "personal_als_features": "personal_als_features.parquet",
        "similar": "similar.parquet",
        "ranked": "recommendations.parquet",
    }

    S3_DATA_PREFIX: str = "recsys/data"
    S3_RECS_PREFIX: str = "recsys/recommendations"

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

    SIMILAR_TOP_N: int = 20_000
    SIMILAR_BATCH: int = 128

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

    LOG_LEVEL: int = logging.INFO


CFG = Config()
RNG = np.random.default_rng(CFG.SEED)

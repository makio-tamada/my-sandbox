"""GloVe (ANN-Benchmarks) をサブサンプルして pgvector に投入する。

- 元データは 1,183,514 x 100 だが、本検証では時間短縮のため SUBSET_SIZE 件だけを使う
- 同梱の `neighbors` は全件基準なので使えない。サブセット上の厳密 top-10 を numpy で再計算する
- L2 正規化してから `vector_cosine_ops` で HNSW を張る（angular = cosine）
"""

from __future__ import annotations

import time
from pathlib import Path

import asyncpg
import h5py
import numpy as np

from .pool_factories import DSN

DATA_PATH = Path(__file__).resolve().parent.parent / ".data" / "glove-100-angular.hdf5"
SUBSET_SIZE = 20_000
N_QUERIES = 200
TOP_K = 10


def _l2_normalize(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


def load_subset() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(corpus_vecs, query_vecs, ground_truth_top10_ids) を返す。"""
    with h5py.File(DATA_PATH, "r") as f:
        corpus = np.asarray(f["train"][:SUBSET_SIZE], dtype=np.float32)
        queries = np.asarray(f["test"][:N_QUERIES], dtype=np.float32)

    corpus = _l2_normalize(corpus)
    queries = _l2_normalize(queries)

    # サブセット上でのコサイン類似度による厳密 top-10 を再計算する
    # (正規化済みなので内積 = コサイン類似度)
    sims = queries @ corpus.T  # (N_QUERIES, SUBSET_SIZE)
    # 上位10件を argpartition で高速に取り出し、その中だけ降順ソートする
    part = np.argpartition(-sims, TOP_K, axis=1)[:, :TOP_K]
    row_idx = np.arange(sims.shape[0])[:, None]
    order = np.argsort(-sims[row_idx, part], axis=1)
    ground_truth = part[row_idx, order]

    return corpus, queries, ground_truth


async def load_into_pgvector(corpus: np.ndarray) -> None:
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.execute("DROP TABLE IF EXISTS docs")
        await conn.execute("CREATE TABLE docs (id integer PRIMARY KEY, embedding vector(100))")
        # asyncpg は vector 型のバイナリエンコーダを持たないため、
        # テキスト表現を渡して SQL 側で ::vector にキャストする executemany で投入する
        records = [
            (i, "[" + ",".join(f"{x:.6f}" for x in vec) + "]") for i, vec in enumerate(corpus)
        ]
        BATCH = 2000
        for start in range(0, len(records), BATCH):
            batch = records[start : start + BATCH]
            await conn.executemany(
                "INSERT INTO docs (id, embedding) VALUES ($1, $2::vector)", batch
            )
        t0 = time.perf_counter()
        await conn.execute(
            "CREATE INDEX ON docs USING hnsw (embedding vector_cosine_ops) "
            "WITH (m=16, ef_construction=64)"
        )
        print(f"HNSW index 作成: {time.perf_counter() - t0:.1f}秒")
    finally:
        await conn.close()


async def prepare() -> tuple[np.ndarray, np.ndarray]:
    """データを準備し、(queries, ground_truth) を返す（recall計算に使う）。"""
    t0 = time.perf_counter()
    corpus, queries, ground_truth = load_subset()
    print(f"データ読み込み+正規化+正解データ再計算: {time.perf_counter() - t0:.1f}秒")
    print(f"corpus={corpus.shape}, queries={queries.shape}, ground_truth={ground_truth.shape}")

    await load_into_pgvector(corpus)
    np.save(Path(__file__).resolve().parent.parent / ".data" / "queries.npy", queries)
    np.save(Path(__file__).resolve().parent.parent / ".data" / "ground_truth.npy", ground_truth)
    return queries, ground_truth


if __name__ == "__main__":
    import asyncio

    asyncio.run(prepare())

# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy>=2.0", "scikit-learn>=1.5"]
# ///
"""ベンチマーク用のベクトルを作る。

Hugging Face Hub に届かない環境なので、ニューラル埋め込みの代わりに
Python ライブラリの docstring 段落を TF-IDF → TruncatedSVD → L2 正規化して 384 次元にする。

    uv run make_vectors.py --root /usr/local/lib/python3.13

出力（data/ は .gitignore 済み）:
    data/xb.npy   コーパス (n_base, dim) float32
    data/xq.npy   クエリ   (n_query, dim) float32
    data/xt.npy   サンプル (n_sample, dim) float32  HNSW のシンク除去リンク用。コーパス・クエリと重ならない
    data/meta.json  段落数・語彙数・SVD の説明分散などの記録
"""

import argparse
import ast
import hashlib
import json
import pathlib
import time
import warnings

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer

HERE = pathlib.Path(__file__).parent


def collect_paragraphs(root: pathlib.Path, min_chars: int) -> list[str]:
    """root 以下の .py から docstring を取り出し、空行区切りの段落に分ける。"""
    paragraphs: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, ValueError, OSError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            doc = ast.get_docstring(node)
            if not doc:
                continue
            for para in doc.split("\n\n"):
                text = " ".join(para.split())
                if len(text) >= min_chars:
                    paragraphs.add(text)
    return sorted(paragraphs)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/usr/local/lib/python3.13")
    parser.add_argument("--n-base", type=int, default=100_000)
    parser.add_argument("--n-query", type=int, default=1_000)
    parser.add_argument("--n-sample", type=int, default=10_000)
    parser.add_argument("--dim", type=int, default=384)
    parser.add_argument("--min-chars", type=int, default=40)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    t0 = time.perf_counter()
    paragraphs = collect_paragraphs(pathlib.Path(args.root), args.min_chars)
    t_collect = time.perf_counter() - t0
    print(f"段落（重複除去後）: {len(paragraphs):,} 件 / {t_collect:.1f} 秒")

    need = args.n_base + args.n_query + args.n_sample
    if len(paragraphs) < need:
        raise SystemExit(f"段落が足りない: {len(paragraphs)} < {need}")
    rng = np.random.default_rng(args.seed)
    idx = rng.permutation(len(paragraphs))[:need]
    base_texts = [paragraphs[i] for i in idx[: args.n_base]]
    query_texts = [paragraphs[i] for i in idx[args.n_base : args.n_base + args.n_query]]
    sample_texts = [paragraphs[i] for i in idx[args.n_base + args.n_query :]]

    t0 = time.perf_counter()
    vec = TfidfVectorizer(sublinear_tf=True, min_df=2, max_features=200_000, dtype=np.float32)
    xb_sparse = vec.fit_transform(base_texts)
    xq_sparse = vec.transform(query_texts)
    svd = TruncatedSVD(n_components=args.dim, algorithm="randomized", n_iter=5, random_state=args.seed)
    xb = svd.fit_transform(xb_sparse).astype(np.float32)
    xq = svd.transform(xq_sparse).astype(np.float32)
    xt = svd.transform(vec.transform(sample_texts)).astype(np.float32)
    t_embed = time.perf_counter() - t0

    # 埋め込みと同じく単位ベクトルにして、内積 = コサイン類似度で検索する
    for x in (xb, xq, xt):
        norms = np.linalg.norm(x, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        x /= norms

    out = HERE / "data"
    out.mkdir(exist_ok=True)
    np.save(out / "xb.npy", xb)
    np.save(out / "xq.npy", xq)
    np.save(out / "xt.npy", xt)
    meta = {
        "root": args.root,
        "n_paragraphs": len(paragraphs),
        "n_base": int(xb.shape[0]),
        "n_query": int(xq.shape[0]),
        "n_sample": int(xt.shape[0]),
        "dim": int(xb.shape[1]),
        "vocab_size": len(vec.vocabulary_),
        "svd_explained_variance_ratio_sum": float(svd.explained_variance_ratio_.sum()),
        "zero_vectors_query": int((np.abs(xq).sum(axis=1) == 0).sum()),
        "seconds_collect": round(t_collect, 1),
        "seconds_embed": round(t_embed, 1),
        "sha256_xb": hashlib.sha256(xb.tobytes()).hexdigest()[:16],
        "sha256_xq": hashlib.sha256(xq.tobytes()).hexdigest()[:16],
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

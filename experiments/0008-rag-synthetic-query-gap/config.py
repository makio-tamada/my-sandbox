"""0008 の設定を 1 箇所に集約する。実行前に固定し、レポートにそのまま書き写す。

**モデル ID を記憶で書かないこと。** 実行前に `claude-api` スキルで現行 ID と料金を確認する。
下の MODEL_ID は CLAUDE.md（2026-11 時点）の現行 ID。
"""

# --- LLM（合成クエリ生成とクエリ拡張に同じモデルを使う。レポートに明記する） ---
MODEL_ID = "claude-haiku-5-5"
TEMPERATURE = 0.0
MAX_TOKENS_SYNTHETIC = 64
MAX_TOKENS_EXPAND = 128

# 合成クエリ生成のプロンプト。SQuAD と埋め込みモデルが英語なので英語で生成させる
SYNTHETIC_PROMPT = (
    "Write one question that can be answered using only the passage below.\n"
    "Output only the question, with no preamble.\n\n"
    "Passage:\n{passage}"
)

# クエリ拡張のプロンプト。言い換えを 2 つ、1 行に 1 つ
EXPAND_PROMPT = (
    "Rewrite the following search query in 2 different ways that keep its meaning.\n"
    "Output exactly 2 lines, one rewrite per line, with nothing else.\n\n"
    "Query: {query}"
)

# --- データ ---
SQUAD_SPLIT = "validation"  # SQuAD v1.1 の dev セット（48 記事）
DEV_ARTICLE_COUNT = 16  # 閾値を決める開発用の記事数。残りが評価用
SEED = 20261126

# --- 検索 ---
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
TOP_K = 5  # Recall@5 / MRR@5
CANDIDATES_PER_QUERY = 20  # 拡張時に各クエリから取る候補数（RRF の入力）
RRF_K = 60  # Reciprocal Rank Fusion の定数

# --- 統計 ---
BOOTSTRAP_ITERS = 2000
# 補足の曲線で振る閾値（上位 1 件のコサイン類似度）
SWEEP_THRESHOLDS = [round(0.20 + 0.05 * i, 2) for i in range(13)]  # 0.20〜0.80

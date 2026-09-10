"""モデル ID とパラメータを 1 箇所に集約する。

比較検証のときはここだけ差し替える。**モデル ID を記憶で書かないこと。**
最新の ID と料金は `claude-api` スキルで確認する（2026-09 時点の現行モデル）:

    claude-opus-5              $5 / $25 per MTok  （既定。迷ったらこれ）
    claude-sonnet-5            $2 / $10 per MTok
    claude-haiku-4-5           $1 / $5  per MTok
    claude-fable-5-1           $10 / $50 per MTok （最も高性能。API の挙動が異なる）
"""

MODEL_ID = "claude-opus-5"
MAX_TOKENS = 16000

# 思考の深さ。low / medium / high / xhigh / max（既定は high）
EFFORT = "high"

# ポリシー判定で拒否された場合に、同一リクエスト内で退避させるモデル
FALLBACK_MODEL = "claude-opus-4-8"
FALLBACK_BETA = "server-side-fallback-2026-06-01"

# /// script
# requires-python = ">=3.12"
# dependencies = ["anthropic>=1.4", "python-dotenv>=1.0"]
# ///
"""Claude API の最小の検証スクリプト。

    uv run main.py

検証で必ず記録すること（レポートの「前提・計測環境」に書く）:
モデル ID、max_tokens、effort、試行回数、入出力トークン数と概算コスト。
"""

import json
from pathlib import Path

from client import build_client
from config import EFFORT, FALLBACK_BETA, FALLBACK_MODEL, MAX_TOKENS, MODEL_ID

PROMPT = "自己紹介を 1 文でしてください。"

# レスポンスを残しておくと、後からレポートを書くときに再確認できる
RUNS_DIR = Path(__file__).parent / "runs"


def ask(client, prompt: str):
    """1 リクエスト送る。

    ポリシー判定で拒否された場合に備えて server-side fallback を有効にしている
    （拒否されると同一リクエスト内で FALLBACK_MODEL が引き継ぐ）。
    不要なら betas と fallbacks を外して client.messages.create に変えてよい。
    """
    return client.beta.messages.create(
        model=MODEL_ID,
        max_tokens=MAX_TOKENS,
        output_config={"effort": EFFORT},
        betas=[FALLBACK_BETA],
        fallbacks=[{"model": FALLBACK_MODEL}],
        messages=[{"role": "user", "content": prompt}],
    )


def extract_text(response) -> str:
    """content は複数種類のブロックの配列。type を見てから .text を読む。"""
    return "".join(block.text for block in response.content if block.type == "text")


def save_run(response, prompt: str, index: int) -> None:
    RUNS_DIR.mkdir(exist_ok=True)
    (RUNS_DIR / f"run_{index:02d}.json").write_text(
        json.dumps(
            {
                "model": response.model,
                "prompt": prompt,
                "stop_reason": response.stop_reason,
                "text": extract_text(response),
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    client = build_client()

    # LLM の出力は決定的ではない。1 回の結果を結論にしない
    trials = 3
    total_in = total_out = 0

    for i in range(1, trials + 1):
        response = ask(client, PROMPT)

        # content を読む前に必ず stop_reason を確認する
        if response.stop_reason == "refusal":
            detail = response.stop_details
            print(f"[{i}] 拒否されました: {detail.category if detail else '不明'}")
            continue

        print(f"[{i}] {extract_text(response)}")
        print(
            f"    model={response.model} "
            f"in={response.usage.input_tokens} out={response.usage.output_tokens}"
        )
        total_in += response.usage.input_tokens
        total_out += response.usage.output_tokens
        save_run(response, PROMPT, i)

    print(f"\n合計トークン: 入力 {total_in} / 出力 {total_out}")
    print("概算コストは claude-api スキルの料金表で計算してレポートに記録すること。")


if __name__ == "__main__":
    main()

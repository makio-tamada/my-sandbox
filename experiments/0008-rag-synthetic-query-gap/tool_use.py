# /// script
# requires-python = ">=3.12"
# dependencies = ["anthropic>=1.4", "python-dotenv>=1.0"]
# ///
"""ツール定義とエージェントループの最小例。

    uv run tool_use.py

tool_runner は「リクエスト → ツール実行 → 結果を返して再リクエスト」の
ループを SDK 側で回してくれる（beta）。ループを自分で制御したい場合は
`claude-api` スキルの manual loop を参照する。
"""

from anthropic import beta_tool

from client import build_client
from config import MAX_TOKENS, MODEL_ID


@beta_tool
def get_weather(location: str, unit: str = "celsius") -> str:
    """指定した地点の現在の天気を返す。

    Args:
        location: 地名。例: 東京
        unit: 温度の単位。celsius または fahrenheit
    """
    # 検証用のダミー実装。実際の検証では本物の処理に差し替える
    return f"{location} は晴れ、22 {unit}"


def main() -> None:
    client = build_client()

    runner = client.beta.messages.tool_runner(
        model=MODEL_ID,
        max_tokens=MAX_TOKENS,
        tools=[get_weather],
        messages=[{"role": "user", "content": "東京の天気を教えてください。"}],
    )

    # 各イテレーションが 1 メッセージ。ツール呼び出しがなくなると止まる
    for message in runner:
        for block in message.content:
            if block.type == "text":
                print(f"[text] {block.text}")
            elif block.type == "tool_use":
                print(f"[tool] {block.name}({block.input})")
        print(
            f"       in={message.usage.input_tokens} out={message.usage.output_tokens}"
        )


if __name__ == "__main__":
    main()

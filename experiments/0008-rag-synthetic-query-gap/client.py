"""API キーの読み込みとクライアント生成。キーの値は決して出力しない。"""

import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv


def build_client() -> anthropic.Anthropic:
    """.env から ANTHROPIC_API_KEY を読み、クライアントを返す。

    リポジトリ直下の .env を探す。未設定なら .env.example を案内して終了する。
    """
    for candidate in [Path.cwd(), *Path.cwd().parents]:
        env_file = candidate / ".env"
        if env_file.exists():
            load_dotenv(env_file)
            break

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit(
            "ANTHROPIC_API_KEY が設定されていません。\n"
            "リポジトリ直下の .env.example を .env にコピーして値を入れてください。"
        )

    # キーは環境変数から SDK が自動で読む。値をコードに書かない
    return anthropic.Anthropic()

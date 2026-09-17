# 0004: 小型株スクリーニング + 値幅ルールのバックテスト

<!-- ここには動かし方だけを書く。結果と考察は reports/0004-jquants-smallcap-backtest.md に書く -->

割安条件（PER / PBR / ROE）と過去の急騰実績で小型株を絞り、利確 / 損切り / 保有上限の
値幅ルールで売買した場合のリターンを、J-Quants API V2 のデータでシミュレーションする。

## 準備

リポジトリ直下の `.env` に J-Quants の API キーを入れる。

```shell
cp .env.example .env
# JQUANTS_API_KEY=... を記入する
```

V2 から認証方式が変わっている。V1 のメール / パスワード（refreshToken → idToken）は廃止され、
[ダッシュボード](https://jpx-jquants.com/)で発行する API キーを `x-api-key` ヘッダに載せる。

```shell
uv sync
```

## 動かし方

```shell
# 1. 実データのカラム名を確認する（3 リクエスト）
uv run 00_explore_schema.py

# 2. 四本値と財務を日付単位で取得して data/ にキャッシュする
#    Free プランは 5 リクエスト/分。1 営業日あたり 2 リクエスト（四本値・財務）。
uv run 01_fetch.py --from 2025-04-01 --to 2026-03-31 --max-requests 20   # まず少しだけ
uv run 01_fetch.py --from 2025-04-01 --to 2026-03-31                     # 続きを取る

# 3. スクリーニングとバックテスト（API は叩かない）
uv run 02_backtest.py
uv run 02_backtest.py --max-per 12 --take-profit 0.20 --stop-loss 0.05   # 条件を振る
```

`01_fetch.py` は取得済みの日をスキップするので、途中で止めても再開できる。
`data/` と `outputs/` は `.gitignore` 済み。

## 所要時間の見積もり

Free プランの 5 リクエスト/分が律速になる。1 営業日あたり四本値 1 + 財務 1 = 2 リクエスト。

| 期間 | 営業日 | リクエスト | 所要時間 |
| --- | --- | --- | --- |
| 1 か月 | 約 21 | 約 42 | 約 9 分 |
| 1 年 | 約 245 | 約 490 | 約 98 分 |
| 2 年 | 約 490 | 約 980 | 約 196 分 |

銘柄ごとに引くと 4000 銘柄 = 4000 リクエスト = 約 13 時間かかるので、日付単位で取る。

## 条件を変える

閾値は `src/config.py` の `ScreenConfig` / `TradeConfig` に集めてある。
`02_backtest.py` のオプションでも上書きできる。

## 品質チェック

```shell
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

`/verify experiments/0004-jquants-smallcap-backtest` でまとめて実行できる。

テストは API を叩かない。合成データでスクリーニング条件と約定ロジックを確かめ、
クライアントはレート制限・ページング・429 リトライを偽のレスポンスで確かめている。

## 構成

| ファイル | 役割 |
| --- | --- |
| `src/config.py` | 閾値と API のフィールド名 |
| `src/jquants.py` | V2 クライアント（`x-api-key` / レート制限 / ページング / 429 リトライ） |
| `src/cache.py` | 日付単位のローカルキャッシュと正規化 |
| `src/screener.py` | 買い候補の抽出（先読み防止を含む） |
| `src/backtest.py` | 値幅ルールの約定シミュレーション |

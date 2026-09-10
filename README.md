# my-sandbox

気になった技術をここで検証していく。

検証 1 件は **Issue → ブランチ → 実装 → レポート → PR** の流れで進み、
成果は `reports/` に残る。過去に何を確かめたかは **[検証レポート索引](reports/README.md)** から辿れる。

## 新しい検証を始める

Claude Code で次を実行すると、Issue の作成・ブランチの作成・雛形の配置までが行われる。

```
/new-exp <検証したいこと>
```

検証が終わったら、レポートの作成・索引の更新・PR の作成までを行う。

```
/wrap-exp
```

**PR のマージは人間が行う。** マージされると `Closes #N` によって Issue が自動でクローズされる。

## 構成

```text
my-sandbox/
├── CLAUDE.md              # 運用ルール（Claude が最初に読む）
├── .claude/
│   ├── commands/          # /new-exp /wrap-exp /verify
│   ├── skills/            # 検証・レポート・計測・LLM・環境構築の作法
│   └── settings.json      # 権限設定
├── .github/               # Issue / PR テンプレート
├── templates/             # 検証の雛形（python-script / python-project / llm-anthropic）
├── experiments/           # 検証コード（NNNN-slug/）
└── reports/               # 成果レポート（NNNN-slug.md）と索引
```

検証コードは `experiments/`、読み返すためのレポートは `reports/` と役割を分けている。
番号 `NNNN` と slug はブランチ名・ディレクトリ名・レポート名の 3 つで一致させる。

## 環境

```shell
mise install                      # Python 3.12 / Node 24
cp .env.example .env              # Claude API を使う検証をする場合
```

Python の依存は `uv` で管理する（`pip` は使わない）。単発の検証は PEP 723 のインラインメタデータ、
規模が出たら `pyproject.toml` に移す。詳細は [CLAUDE.md](CLAUDE.md) を参照。

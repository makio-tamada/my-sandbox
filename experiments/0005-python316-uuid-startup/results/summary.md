## uuid 1 回あたりの時間（ns、7 回の中央値。括弧内は最小〜最大）

| 操作 | 3.15.2 | 3.16.0a2 C | 3.16.0a2 純Python | 3.16 C / 3.16 純Py | 3.16 C / 3.15.2 |
| --- | ---: | ---: | ---: | ---: | ---: |
| uuid4() | 711 (702〜725) | 160 (158〜162) | 730 (710〜770) | 4.56x | 4.44x |
| uuid7() | 1136 (1122〜1186) | 158 (158〜162) | 1074 (1057〜1202) | 6.79x | 7.18x |
| UUID(str) | 544 (530〜568) | 96 (96〜97) | 539 (523〜606) | 5.60x | 5.64x |
| UUID(bytes=) | 410 (406〜411) | 63 (63〜64) | 418 (410〜484) | 6.62x | 6.49x |
| str(UUID) | 274 (269〜309) | 34 (33〜34) | 264 (256〜310) | 7.83x | 8.12x |

## 正しさの確認

- 3.15.2（uuid4 実装: Python, UUID クラス: uuid）: {'uuid4_all_version4': True, 'uuid4_all_rfc_variant': True, 'uuid4_unique': True, 'uuid7_all_version7': True, 'uuid7_strictly_increasing': True, 'uuid7_unique': True, 'roundtrip_str_bytes': True}
- 3.16.0a2 C（uuid4 実装: C, UUID クラス: uuid）: {'uuid4_all_version4': True, 'uuid4_all_rfc_variant': True, 'uuid4_unique': True, 'uuid7_all_version7': True, 'uuid7_strictly_increasing': True, 'uuid7_unique': True, 'roundtrip_str_bytes': True, 'c_vs_py_same_int': True, 'c_vs_py_same_str': True, 'c_vs_py_eq': True, 'c_vs_py_same_hash': False}
- 3.16.0a2 純Python（uuid4 実装: Python, UUID クラス: uuid）: {'uuid4_all_version4': True, 'uuid4_all_rfc_variant': True, 'uuid4_unique': True, 'uuid7_all_version7': True, 'uuid7_strictly_increasing': True, 'uuid7_unique': True, 'roundtrip_str_bytes': True}

## 互換性の確認

| 項目 | 3.15.2 | 3.16.0a2 |
| --- | --- | --- |
| pickle: uuid4() の往復 | True | クラッシュ（シグナル 11） |
| pickle: UUID(str) の往復 | True | クラッシュ（シグナル 11） |
| pickle: UUID(str, is_safe=unknown) の往復 | True | True |
| pickle: uuid1() の往復 | True | True |
| copy.deepcopy: UUID を含む dict | True | クラッシュ（シグナル 11） |
| copy.copy: uuid7() | True | クラッシュ（シグナル 11） |
| hash(u) == hash(u.int) | True | False |
| C 版と純 Python 版の同値オブジェクトが set で 1 件になる | True | False |
| fork 後に親子の uuid4() が重複しない（各 100,000 件） | True | True |

## 起動時間（ms、200 回の中央値。括弧内は p10〜p90）

| コマンド | 3.15.2 | 3.16.0a2 | 差（3.16 − 3.15） |
| --- | ---: | ---: | ---: |
| `-I -c pass` | 9.67 (9.26〜13.01) | 9.30 (8.92〜12.98) | -0.37 ms (-3.8%) |
| `-c pass（site あり）` | 9.40 (9.24〜9.67) | 9.00 (8.84〜9.32) | -0.39 ms (-4.2%) |
| `-I -c 'import 標準 6 モジュール'` | 22.99 (22.40〜26.84) | 21.96 (21.44〜25.83) | -1.03 ms (-4.5%) |

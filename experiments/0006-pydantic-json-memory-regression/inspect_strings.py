"""結果の中で同じ内容の文字列が何個の別オブジェクトになっているかを数える（メモリ差の手がかり）。

    <venv>/bin/python inspect_strings.py --payload payload.json

root_dict（RootModel[dict[str, object]]）と from_json の結果について、
全 items の attributes のキー（"key0"〜"key29"）・値（""）・kind の値（"thing" など）が
それぞれ何個の別オブジェクトとして作られたか（id の種類数）を JSON 1 行で出す。
"""

import argparse
import json
from pathlib import Path

import pydantic
import pydantic_core
from pydantic import RootModel


class Plain(RootModel[dict[str, object]]):
    pass


def count(items: list[dict]) -> dict[str, int]:
    keys, values, kinds, ids = set(), set(), set(), set()
    for it in items:
        ids.add(id(it["id"]))
        for k, v in it["attributes"].items():
            keys.add(id(k))
            values.add(id(v))
        for k, v in it["kind"].items():
            kinds.add(id(k))
            kinds.add(id(v))
    return {
        "items": len(items),
        "attr_key_objects": len(keys),
        "attr_value_objects": len(values),
        "kind_str_objects": len(kinds),
        "id_str_objects": len(ids),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", type=Path, required=True)
    args = parser.parse_args()
    data = args.payload.read_bytes()

    root = Plain.model_validate_json(data).root
    out = {
        "pydantic": pydantic.VERSION,
        "pydantic_core": pydantic_core.__version__,
        "root_dict": count(root["items"]),
    }
    del root
    out["from_json"] = count(pydantic_core.from_json(data)["items"])
    print(json.dumps(out))


if __name__ == "__main__":
    main()

"""pydantic#14234 の再現コード（報告者が Issue に載せたものをそのまま使う）。

    <venv>/bin/python repro_issue14234.py

出典: https://github.com/pydantic/pydantic/issues/14234
"""

import gc
import json
import resource
import sys

import pydantic
import pydantic_core
from pydantic import RootModel


class Plain(RootModel):
    root: dict[str, object]


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def build_payload(n_obj: int = 100_000, n_attrs: int = 30) -> str:
    items = []
    for i in range(n_obj):
        items.append(
            {
                "id": f"/objects/{i:07d}",
                "kind": {"name": "thing", "version": "1.0.0"},
                "attributes": {f"key{j}": "" for j in range(n_attrs)},
            }
        )
    return json.dumps({"items": items})


def main() -> None:
    data = build_payload()
    gc.collect()
    base = rss_mb()
    Plain.model_validate_json(data.encode())
    gc.collect()
    retained = rss_mb() - base
    print(f"python {sys.version.split()[0]}")
    print(f"pydantic {pydantic.VERSION}, pydantic-core {pydantic_core.__version__}")
    print(f"json={len(data) / 1e6:.0f}MB  retained_after_validate={retained:.0f}MB")


if __name__ == "__main__":
    main()

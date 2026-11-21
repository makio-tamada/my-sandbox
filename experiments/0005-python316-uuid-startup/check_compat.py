"""uuid の C 実装まわりの互換性を、項目ごとに別プロセスで確かめる。

    python3 check_compat.py /path/to/python3.15 /path/to/python3.16

セグメンテーション違反でも他の項目を続けられるよう、各項目を子プロセスで実行し、
終了コードと標準出力の最終行を記録する。結果は JSON で標準出力に出す。
"""

import json
import subprocess
import sys

PRELUDE = "import copy, os, pickle, uuid\ns = '6f2c1e0a-3b4d-4c5e-8f60-718293a4b5c6'\n"

CASES = {
    "pickle: uuid4() の往復": "u = uuid.uuid4(); print(pickle.loads(pickle.dumps(u)) == u)",
    "pickle: UUID(str) の往復": "u = uuid.UUID(s); print(pickle.loads(pickle.dumps(u)) == u)",
    "pickle: UUID(str, is_safe=unknown) の往復": (
        "u = uuid.UUID(s, is_safe=uuid.SafeUUID.unknown); print(pickle.loads(pickle.dumps(u)) == u)"
    ),
    "pickle: uuid1() の往復": "u = uuid.uuid1(); print(pickle.loads(pickle.dumps(u)) == u)",
    "copy.deepcopy: UUID を含む dict": "d = {'id': uuid.uuid4()}; print(copy.deepcopy(d) == d)",
    "copy.copy: uuid7()": "u = uuid.uuid7(); print(copy.copy(u) == u)",
    "hash(u) == hash(u.int)": "u = uuid.UUID(s); print(hash(u) == hash(u.int))",
    "C 版と純 Python 版の同値オブジェクトが set で 1 件になる": (
        "py = getattr(uuid, '_py_UUID', uuid.UUID); print(len({uuid.UUID(s), py(s)}) == 1)"
    ),
    "fork 後に親子の uuid4() が重複しない（各 100,000 件）": (
        "uuid.uuid4()\n"  # fork 前に一度生成してキャッシュを温める
        "r, w = os.pipe()\n"
        "pid = os.fork()\n"
        "if pid == 0:\n"
        "    os.close(r)\n"
        "    data = b''.join(uuid.uuid4().bytes for _ in range(100_000))\n"
        "    with os.fdopen(w, 'wb') as f: f.write(data)\n"
        "    os._exit(0)\n"
        "os.close(w)\n"
        "parent = {uuid.uuid4().bytes for _ in range(100_000)}\n"
        "with os.fdopen(r, 'rb') as f: data = f.read()\n"
        "os.waitpid(pid, 0)\n"
        "child = {data[i:i + 16] for i in range(0, len(data), 16)}\n"
        "print(len(parent) == 100_000 and len(child) == 100_000 and not (parent & child))"
    ),
}


def run_case(python: str, code: str) -> dict[str, object]:
    proc = subprocess.run(
        [python, "-c", PRELUDE + code],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    lines = proc.stdout.strip().splitlines()
    if proc.returncode < 0:
        outcome = f"クラッシュ（シグナル {-proc.returncode}）"
    elif proc.returncode != 0:
        outcome = "例外: " + (proc.stderr.strip().splitlines() or ["?"])[-1]
    else:
        outcome = lines[-1] if lines else "(出力なし)"
    return {"returncode": proc.returncode, "outcome": outcome}


def main() -> None:
    pythons = sys.argv[1:]
    results = {
        name: {p: run_case(p, code) for p in pythons} for name, code in CASES.items()
    }
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()

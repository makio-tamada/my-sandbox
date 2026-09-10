"""雛形が壊れていないことだけを確かめるテスト。"""

from src.experiment import run


def test_run() -> None:
    assert run() == "ok"

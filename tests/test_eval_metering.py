"""MeteringBackend:透明代理不改行为,只记账。零真实模型。"""
import pytest

from conftest import FakeBackend
from evals.metering import MeteringBackend


def test_metering_passthrough_and_records():
    fb = FakeBackend(lambda s, u: "产出文本")
    m = MeteringBackend(fb)
    out = m.complete("SYS", "USER输入", max_chars=600)
    assert out == "产出文本"
    assert fb.calls == [("SYS", "USER输入")]          # 透传不改行为
    r = m.records[0]
    assert r.system_prompt == "SYS"
    assert r.user_chars == len("USER输入")
    assert r.output_chars == len("产出文本")
    assert r.max_chars == 600
    assert r.elapsed_s >= 0


def test_metering_on_chunk_passthrough():
    got: list[str] = []
    m = MeteringBackend(FakeBackend(lambda s, u: "流式"))
    m.complete("S", "U", on_chunk=got.append)
    assert got == ["流式"]                             # FakeBackend 的 on_chunk 回放仍生效


def test_metering_propagates_backend_error_without_fake_record():
    def boom(s, u):
        raise RuntimeError("后端炸了")
    m = MeteringBackend(FakeBackend(boom))
    with pytest.raises(RuntimeError):
        m.complete("S", "U")
    assert m.records == []                             # 失败调用不记成功账

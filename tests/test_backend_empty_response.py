"""200 空响应的两道兜底:补满预算重来 / 正文放错字段。

用户实报 2026-08-23(自建 OpenAI 兼容端点 + 本地思考型模型):写章拿到 200,但 content 是空的。
两种成因长得一模一样,判据只有 `finish_reason`——分不开就会把半截思维链当正文写进作者的书里。
这里用假 client 打桩,不联网。
"""
from __future__ import annotations

import pytest

from loom.backends import _THINK_BUDGET, LoomBackendError, OpenAICompatBackend
from loom.config import Config


class _Msg:
    def __init__(self, content, reasoning=None):
        self.content = content
        if reasoning is not None:
            self.reasoning_content = reasoning


class _Choice:
    def __init__(self, content, finish, reasoning=None):
        self.message = _Msg(content, reasoning)
        self.finish_reason = finish


class _Resp:
    def __init__(self, content, finish, reasoning=None):
        self.choices = [_Choice(content, finish, reasoning)]


class _FakeCompletions:
    """按脚本逐次返回;每次调用记下 max_tokens。"""

    def __init__(self, script):
        self.script = list(script)
        self.budgets: list[int] = []

    def create(self, **kw):
        self.budgets.append(kw["max_tokens"])
        return self.script.pop(0)


def _be(monkeypatch, script, provider="openai_compat") -> tuple[OpenAICompatBackend, _FakeCompletions]:
    """默认打自定义端点这一档:它的预算按 max_chars 现算(不是 DeepSeek 那个 65536 常数),
    正是「思考吃光预算」这个 bug 的现场。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("LOOM_OPENAI_COMPAT_KEY", "sk-test")
    cfg = (Config(provider="deepseek", model="deepseek-v4-pro") if provider == "deepseek"
           else Config(provider="openai_compat", model="qwen3-local",
                       base_url="http://127.0.0.1:8000/v1"))
    be = OpenAICompatBackend(cfg, provider)
    comp = _FakeCompletions(script)

    class _Chat:
        completions = comp

    be._client = type("C", (), {"chat": _Chat()})()
    return be, comp


def test_思考被腰斩时补满预算重来_而不是把半截思维链当正文(monkeypatch):
    """finish_reason=length + 正文空 = reasoning 把 max_tokens 吃光了。
    此刻 reasoning_content 里是【没说完的思考】,拿它入库等于把「嗯,这章先写验伤……」
    写进作者的书。正确动作是补一次满预算。"""
    be, comp = _be(monkeypatch, [
        _Resp("", "length", "嗯,这一章应该先写验伤,再让他遇敌"),
        _Resp("他没说话。火把的光爬上矿壁。", "stop", "(思考若干)"),
    ])
    out = be.complete("s", "u", max_chars=1200)
    assert out == "他没说话。火把的光爬上矿壁。"
    assert "验伤" not in out, "半截思维链绝不许当正文交出去"
    assert comp.budgets[0] < _THINK_BUDGET, "第一次是按 max_chars 现算的小预算"
    assert comp.budgets[1] == _THINK_BUDGET, "第二次要给满预算,否则重来还是同样被腰斩"


def test_已经是满预算的供应商不做无谓重试(monkeypatch):
    """DeepSeek 那一档 `_budget_tokens` 恒返回 65536,再重来一次还是同样被腰斩——
    白烧一次钱。只有【预算还能加】的时候才值得重试。"""
    be, comp = _be(monkeypatch, [_Resp("", "length", "半截思考")], provider="deepseek")
    with pytest.raises(LoomBackendError):
        be.complete("s", "u", max_chars=1200)
    assert len(comp.budgets) == 1 and comp.budgets[0] == _THINK_BUDGET


def test_正文放错字段时采信思考字段(monkeypatch):
    """finish_reason=stop 且正文空、思考非空 = 模型把整段回答塞进 reasoning_content 了
    (部分本地部署的 GLM/Qwen 是这个行为)。这时它就是正文。"""
    be, comp = _be(monkeypatch, [_Resp("", "stop", "他没说话。火把的光爬上矿壁。")])
    assert be.complete("s", "u", max_chars=1200) == "他没说话。火把的光爬上矿壁。"
    assert len(comp.budgets) == 1, "正常收尾不该多打一次"


def test_两道兜底都不成立时照旧报错_绝不返回空串(monkeypatch):
    """空响应闸的底线没变:兜不住就报错,绝不把空串往下传去覆盖用户数据。"""
    be, _ = _be(monkeypatch, [_Resp("", "length", ""), _Resp("", "length", "")])
    with pytest.raises(LoomBackendError):
        be.complete("s", "u", max_chars=1200)


def test_正常返回不额外多打一次(monkeypatch):
    """兜底只在正文为空时才动——正常路径零额外开销、零额外花费。"""
    be, comp = _be(monkeypatch, [_Resp("正文在此。", "stop")])
    assert be.complete("s", "u", max_chars=1200) == "正文在此。"
    assert len(comp.budgets) == 1


def test_流式一条正文帧都没发时回退非流式并补发给前端(monkeypatch):
    """有的端点流里只发 reasoning、正文帧一条不发。回退非流式重取,
    拿到了要补发给 on_chunk——否则作者盯着一片空白,以为卡死了。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    be = OpenAICompatBackend(Config(provider="deepseek", model="deepseek-v4-pro"), "deepseek")
    comp = _FakeCompletions([_Resp("他没说话。", "stop")])

    class _Chat:
        completions = comp

    def create(**kw):
        if kw.get("stream"):
            return iter([])          # 空流:一帧正文都没有
        return comp.create(**kw)

    _Chat.completions = type("X", (), {"create": staticmethod(create)})()
    be._client = type("C", (), {"chat": _Chat()})()

    seen: list[str] = []
    assert be.complete("s", "u", max_chars=1200, on_chunk=seen.append) == "他没说话。"
    assert "".join(seen) == "他没说话。", "兜底结果要补发给前端"

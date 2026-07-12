"""旅程用例层:锁+cheap 路由+委托 journey;端点薄壳不在此测(server 是纯转发)。"""
from conftest import FakeBackend, const

from loom import usecases


def test_journey_state_fresh(project):
    s = usecases.journey_state(project)
    assert s["current"] == "立项"


def test_journey_card_routes_cheap_backend(project, monkeypatch):
    fake = FakeBackend(const("问:核心题材?\n- 重生复仇\n- 无敌流"))
    monkeypatch.setattr(usecases, "cheap_backend", lambda cfg: fake)   # cheap 优先
    out = usecases.journey_card(project)
    assert out["card"]["question"] == "核心题材?"
    assert len(fake.calls) == 1


def test_journey_card_falls_back_to_main_backend(project, monkeypatch):
    fake = FakeBackend(const("问:核心题材?\n- A\n- B"))
    monkeypatch.setattr(usecases, "cheap_backend", lambda cfg: None)   # cheap 空 → 主模型
    monkeypatch.setattr(usecases, "get_backend", lambda cfg: fake)
    out = usecases.journey_card(project)
    assert len(fake.calls) == 1 and out["card"] is not None


def test_journey_answer_and_goto(project, monkeypatch):
    fake = FakeBackend(const("格:平台\n问:发哪个平台?\n- 起点\n- 番茄"))
    monkeypatch.setattr(usecases, "cheap_backend", lambda cfg: fake)
    usecases.journey_card(project)
    out = usecases.journey_answer(project, "番茄")
    assert out["landed"].endswith("立项卡.md")
    s = usecases.journey_goto(project, "立项", skip=True)   # 门禁段禁跳:静默降级为聚焦,不前进(Task 5)
    assert s["current"] == "立项"

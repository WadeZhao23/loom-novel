"""usecases 单一编排宿主:learn 基线 cli/server 同源 / LearnReport 形状 /
写锁覆盖新端点(file PUT 豁免)/ write 前置三态。"""
from __future__ import annotations

import pytest

from loom import ledger, paths, usecases
from loom.fingerprint import neutral_default

from conftest import FakeBackend, const

VALID_FP = ("# 写作指纹\n\n## 句式偏好\n- 短句为主,单句成段,动作收尾。\n"
            "- 对白只留半句,潜台词留给读者。\n\n## 节奏\n- 紧处短句快切。\n\n"
            "## anchor 例句\n> 风停了。他把刀收回鞘里,没回头。\n")


def _seed_chapter(project, snapshot: str, edited: str) -> None:
    (project / "正文" / ".原稿").mkdir(parents=True, exist_ok=True)
    (project / "正文" / ".原稿" / "第1章.md").write_text(snapshot, encoding="utf-8")
    (project / "正文" / "第1章.md").write_text(edited, encoding="utf-8")


# ---------------------------------------------------------------- learn 基线同源
def test_learn_baseline_is_neutral_default_when_fingerprint_missing(project):
    # cli 曾用 "" 当旧基线(server 用 neutral_default):缺指纹文件时 changes 全量误报。
    # 现在双入口同走 usecases.learn_chapter,基线只有一处。
    (project / paths.FINGERPRINT_REL).unlink()
    _seed_chapter(project, "原始的一句话。", "我手改后的一句话。")
    new_fp = neutral_default().rstrip() + "\n- 新学到的一条规则。\n"

    rep = usecases.learn_chapter(project, 1, FakeBackend(const(new_fp)))

    assert "- 新学到的一条规则。" in rep.changes["added"]
    assert len(rep.changes["added"]) <= 2      # "" 基线会把整份默认指纹全量误报成 added
    assert rep.changes["removed"] == []


# ---------------------------------------------------------------- LearnReport 形状
def test_learn_report_shape_and_recap(project):
    _seed_chapter(project, "原始的一句话。", "我手改后的、更像我的一句话。")

    def respond(system, user):
        if "剧情脊柱" in system:               # 写后摘要(recap)调用
            return "摘要:主角觉醒金手指。\n伏笔:\n- [埋设] 神秘玉佩来历"
        return VALID_FP

    rep = usecases.learn_chapter(project, 1, FakeBackend(respond),
                                 appraisal_backend=FakeBackend(respond))

    assert "潜台词留给读者" in rep.fingerprint
    assert rep.changes["added"]
    assert "[AI回顾]" in rep.card              # 卡章纲全文回传(HTTP 响应兼容,前端自己抠)
    # recap 下沉:第 N 章 [AI回顾] 块已在引擎层抠好(app.js extractRecap 的 Python 版)
    assert rep.recap.startswith("[AI回顾]") and "主角觉醒金手指" in rep.recap
    assert isinstance(rep.world_supp, str) and isinstance(rep.chars_supp, str)
    assert isinstance(rep.warn, str)


# ---------------------------------------------------------------- write 前置三态
def test_write_precheck_three_states(project):
    out = paths.chapter_path(project, 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("# 第1章\n\n正文。\n", encoding="utf-8")
    snap = paths.snapshot_path(project, 1)
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text(out.read_text(encoding="utf-8"), encoding="utf-8")   # .原稿 快照(_has_loom_chapter 判据)
    ledger.record_snapshot(project, 1, out.read_text(encoding="utf-8"))   # 造 Loom 章 → 门禁豁免
    assert usecases.write_precheck(project, 1, True) is None              # force 放行
    rej = usecases.write_precheck(project, 1, False)
    assert rej["code"] == "chapter_exists"
    out.write_text("# 第1章\n\n我手改过的正文。\n", encoding="utf-8")
    assert usecases.write_precheck(project, 1, False)["code"] == "chapter_drifted"


# ---------------------------------------------------------------- 锁:用例层直接拒
def test_locked_usecases_raise_project_busy(project):
    lock = usecases.try_lock(project)
    assert lock is not None
    try:
        with pytest.raises(usecases.ProjectBusyError):
            usecases.learn_chapter(project, 1, FakeBackend(const(VALID_FP)))
        with pytest.raises(usecases.ProjectBusyError):
            usecases.seed_fingerprint(project, text="随便一段样本")   # 锁先于建后端,免 key 也能测
    finally:
        lock.release()


# ---------------------------------------------------------------- 锁:新覆盖端点(HTTP 面)
def test_lock_covers_new_endpoints_but_not_file_put(project):
    pytest.importorskip("httpx")
    from starlette.testclient import TestClient
    import loom.server as server

    lock = usecases.try_lock(project)
    assert lock is not None
    root = str(project)
    try:
        client = TestClient(server.app, base_url="http://127.0.0.1")
        busy_posts = [
            ("/api/rewrite/apply", {"root": root, "chapter": 1, "content": "x",
                                    "old_span": "a", "new_span": "b"}),
            ("/api/chapter/delete", {"root": root, "n": 1}),
            ("/api/chapter/insert", {"root": root, "n": 0}),
            ("/api/chapter/move", {"root": root, "n": 1, "direction": "up"}),
            ("/api/learn/revert", {"root": root, "chapter": 1}),
            ("/api/history/restore", {"root": root, "rel": "正文/第1章.md", "id": "x"}),
        ]
        for url, body in busy_posts:
            r = client.post(url, json=body)
            assert r.status_code == 409, url
            assert r.json()["code"] == "project_busy", url
            assert "正在写作中" in r.json()["error"], url
        # 【红线】外置大脑保存豁免不锁:整章生成几分钟,期间必须能存世界观
        r = client.put("/api/file", json={"root": root, "rel": "外置大脑/世界观.md",
                                          "content": "# 世界观\n\n新设定。\n"})
        assert r.status_code == 200 and r.json()["ok"] is True
    finally:
        lock.release()

    # 锁释放后不再 409(删不存在的章 → 业务 400,不是 project_busy)
    client = TestClient(server.app, base_url="http://127.0.0.1")
    r = client.post("/api/chapter/delete", json={"root": root, "n": 99})
    assert r.status_code == 400


# ---------------------------------------------------------------- 起书完整性门禁
def test_project_state_exposes_gate(project):
    st = usecases.project_state(project)
    assert st["writing_unlocked"] is False
    assert st["missing"] == ["立项", "世界观", "人物", "卡章纲"]

"""导入铺底:文件名启发路由(纯字符串,零 LLM)。写作指纹不是桶。"""
from loom.importer import BUCKETS, route_files


def test_confident_routing():
    r = route_files(["第一卷章纲.md", "主角小传.md", "力量体系设定.md", "势力地理.md"])
    assert r["卡章纲"] == ["第一卷章纲.md"]
    assert r["人物"] == ["主角小传.md"]
    assert set(r["世界观"]) == {"力量体系设定.md", "势力地理.md"}
    assert r["unknown"] == []


def test_optional_brain_buckets():
    r = route_files(["投稿定位.md", "敏感词自查.md", "文风范文.md"])
    assert r["立项卡"] == ["投稿定位.md"]
    assert r["违禁词"] == ["敏感词自查.md"]
    assert r["文风参考"] == ["文风范文.md"]


def test_ambiguous_and_unknown_fall_to_unknown():
    r = route_files(["人物大纲.md", "随笔.md", "readme.md"])
    assert "人物大纲.md" in r["unknown"]   # 撞人物+大纲两类 → 让作者定
    assert "随笔.md" in r["unknown"] and "readme.md" in r["unknown"]


def test_fingerprint_is_never_a_bucket():
    assert "写作指纹" not in BUCKETS
    r = route_files(["写作指纹.md", "文风指纹.md"])
    # 「写作指纹」不路由(它是 learn 蒸出的、不接受粘贴);「文风X」也不硬塞指纹,撞不到唯一类→unknown
    assert "写作指纹.md" in r["unknown"]


def test_import_folder_lands_files(project, tmp_path):
    # project fixture 只借它的 scaffold 能力;这里独立建源资料夹 + 目标 parent
    from loom import importer
    from loom.paths import CARD_REL, CHARS_DIR_REL, WORLD_DIR_REL
    src = tmp_path / "我的设定"
    (src / "人物").mkdir(parents=True)
    (src / "力量体系.md").write_text("# 力量体系\n\n凡境→筑基→金丹。", encoding="utf-8")
    (src / "人物" / "主角·沈砚.md").write_text("# 沈砚\n\n- 底线:不杀无辜。", encoding="utf-8")
    (src / "大纲.md").write_text("第一卷:复仇。", encoding="utf-8")
    (src / "第二卷章纲.md").write_text("第二卷:夺宝。", encoding="utf-8")

    routing = {"世界观": ["力量体系.md"], "人物": ["主角·沈砚.md"],
               "卡章纲": ["大纲.md", "第二卷章纲.md"],
               "立项卡": [], "违禁词": [], "文风参考": []}
    root = importer.import_folder(src, "沈砚传", routing, tmp_path / "书库")

    # 目录桶:一份一文件,原样不改字,占位模板已清(不再有 力量体系 的空模板/主角·未命名)
    world = (root / WORLD_DIR_REL)
    assert (world / "力量体系.md").read_text(encoding="utf-8") == "# 力量体系\n\n凡境→筑基→金丹。"
    assert not (world / "金手指.md").exists()   # 收了文件的桶,其余出厂占位模板被清掉(免真假混着)
    chars = (root / CHARS_DIR_REL)
    assert (chars / "主角·沈砚.md").exists() and not (chars / "主角·未命名.md").exists()
    assert (chars / "成长档案.md").exists()          # 成长档案(AI 自留地)永远保留

    # 单文件桶:多份拼接 + 溯源头,原文都在
    card = (root / CARD_REL).read_text(encoding="utf-8")
    assert "## 来自:大纲.md" in card and "第一卷:复仇。" in card
    assert "## 来自:第二卷章纲.md" in card and "第二卷:夺宝。" in card


def test_import_folder_sanitizes_and_dedups_names(project, tmp_path):
    from loom import importer
    from loom.paths import WORLD_DIR_REL
    src = tmp_path / "s"
    (src / "a").mkdir(parents=True)
    (src / "b").mkdir(parents=True)
    (src / "a" / "设定.md").write_text("A", encoding="utf-8")
    (src / "b" / "设定.md").write_text("B", encoding="utf-8")   # 同名撞车
    routing = {"世界观": ["设定.md", "设定.md"], "人物": [], "卡章纲": [],
               "立项卡": [], "违禁词": [], "文风参考": []}
    root = importer.import_folder(src, "去重书", routing, tmp_path / "lib")
    world = list((root / WORLD_DIR_REL).glob("设定*.md"))
    assert len(world) == 2   # 两份同名都落盘,第二份自动改名不覆盖


def test_import_dir_bucket_is_byte_verbatim(tmp_path):
    from loom import importer
    from loom.paths import WORLD_DIR_REL
    src = tmp_path / "s"; src.mkdir()
    raw = "# 设定\r\n\r\n凡境→筑基。\r\n".encode("utf-8")   # CRLF
    (src / "力量.md").write_bytes(b"\xef\xbb\xbf" + raw)      # + BOM
    routing = {"世界观": ["力量.md"], "人物": [], "卡章纲": [], "立项卡": [], "违禁词": [], "文风参考": []}
    root = importer.import_folder(src, "保真书", routing, tmp_path / "lib")
    assert (root / WORLD_DIR_REL / "力量.md").read_bytes() == b"\xef\xbb\xbf" + raw   # 一字节不改


def test_import_single_bucket_tolerates_gbk_and_strips_bom(tmp_path):
    from loom import importer
    from loom.paths import CARD_REL
    src = tmp_path / "s"; src.mkdir()
    (src / "大纲.md").write_bytes("第一卷:复仇。".encode("gbk"))   # 非 UTF-8,旧版不崩
    routing = {"卡章纲": ["大纲.md"], "世界观": [], "人物": [], "立项卡": [], "违禁词": [], "文风参考": []}
    root = importer.import_folder(src, "GBK书", routing, tmp_path / "lib")
    assert "复仇" in (root / CARD_REL).read_text(encoding="utf-8")


def test_import_rolls_back_on_write_failure(tmp_path, monkeypatch):
    from loom import importer
    src = tmp_path / "s"; (src / "a").mkdir(parents=True)
    (src / "力量.md").write_text("设定", encoding="utf-8")
    calls = {"n": 0}
    real = importer.atomic_write_text
    def boom(path, text):
        calls["n"] += 1
        if calls["n"] >= 1: raise OSError("disk full")
        return real(path, text)
    monkeypatch.setattr(importer, "atomic_write_text", boom)
    routing = {"世界观": [], "人物": [], "卡章纲": ["力量.md"], "立项卡": [], "违禁词": [], "文风参考": []}
    import pytest
    with pytest.raises(OSError):
        importer.import_folder(src, "回滚书", routing, tmp_path / "lib")
    assert not (tmp_path / "lib" / "回滚书").exists()   # 半成品已清,不留orphan


def test_import_summary_flags_degradations(project, tmp_path):
    from loom import importer
    src = tmp_path / "s"; src.mkdir()
    # 世界观文件名不含硬设定关键词 → _hardfacts_for 零命中;章纲段落式;无正文
    (src / "背景故事.md").write_text("# 背景\n\n一个架空王朝的故事。", encoding="utf-8")
    (src / "剧情大纲.md").write_text("主角复仇的三幕故事。", encoding="utf-8")
    routing = {"世界观": ["背景故事.md"], "人物": [], "卡章纲": ["剧情大纲.md"],
               "立项卡": [], "违禁词": [], "文风参考": []}
    root = importer.import_folder(src, "降级书", routing, tmp_path / "lib")
    rep = importer.import_summary(root, routing)
    assert rep["placed"]["世界观"] == 1 and rep["placed"]["卡章纲"] == 1
    joined = " ".join(rep["notes"])
    assert "硬设定" in joined       # 世界观零命中 → 提示专名可能漂
    assert "时间轴" in joined or "自动记忆" in joined   # 段落式章纲 → 自动记忆暂不挂
    assert "中性文风" in joined or "写作指纹" in joined  # 无正文 → 中性文风


def test_summary_world_no_warn_when_hardfact_hit(tmp_path):
    # 文件名命中硬设定关键词(如「阵营」「势力」)→ 真实硬设定直送会保护 → 不报警
    from loom import importer
    src = tmp_path / "s"; src.mkdir()
    (src / "阵营势力.md").write_text("# 阵营\n\n三大阵营。", encoding="utf-8")
    routing = {"世界观": ["阵营势力.md"], "人物": [], "卡章纲": [], "立项卡": [], "违禁词": [], "文风参考": []}
    root = importer.import_folder(src, "阵营书", routing, tmp_path / "l1")
    assert not any("硬设定" in n for n in importer.import_summary(root, routing)["notes"])


def test_summary_world_warns_when_no_hardfact(tmp_path):
    from loom import importer
    src = tmp_path / "s"; src.mkdir()
    (src / "背景杂谈.md").write_text("# 背景\n\n随便写的。", encoding="utf-8")
    routing = {"世界观": ["背景杂谈.md"], "人物": [], "卡章纲": [], "立项卡": [], "违禁词": [], "文风参考": []}
    root = importer.import_folder(src, "背景书", routing, tmp_path / "l2")
    assert any("硬设定" in n for n in importer.import_summary(root, routing)["notes"])


def test_summary_world_spoiler_section_still_warns(tmp_path):
    # 势力=硬设定kw 但 真相=剧透,deny 压过 → 世界观无受保护小节 → 报警(与真实口径一致)
    from loom import importer
    src = tmp_path / "s"; src.mkdir()
    (src / "势力真相.md").write_text("# 真相\n\n终极反转。", encoding="utf-8")
    routing = {"世界观": ["势力真相.md"], "人物": [], "卡章纲": [], "立项卡": [], "违禁词": [], "文风参考": []}
    root = importer.import_folder(src, "真相书", routing, tmp_path / "l3")
    assert any("硬设定" in n for n in importer.import_summary(root, routing)["notes"])


def test_import_endpoints(tmp_path):
    from fastapi.testclient import TestClient
    from loom.server import app
    src = tmp_path / "陈的资料"
    (src / "人物").mkdir(parents=True)
    (src / "力量设定.md").write_text("# 力量\n\n九阶。", encoding="utf-8")
    (src / "人物" / "主角.md").write_text("# 主角\n\n- 底线:护道。", encoding="utf-8")
    (src / "总纲.md").write_text("三卷复仇。", encoding="utf-8")
    (src / "随手记.md").write_text("零碎想法。", encoding="utf-8")
    c = TestClient(app, base_url="http://127.0.0.1")

    r = c.post("/api/project/import/scan", json={"folder": str(src)})
    assert r.status_code == 200
    d = r.json()
    assert d["name_suggest"] == "陈的资料"
    assert "力量设定.md" in d["routed"]["世界观"] and "主角.md" in d["routed"]["人物"]
    # M3:「纲」收进卡章纲关键词 → 「总纲」自动落卡章纲;「随手记」仍零命中,落 unknown 交作者指认
    assert "总纲.md" in d["routed"]["卡章纲"]
    assert "随手记.md" in d["unknown"]

    # 作者把 unknown「随手记」指认进世界观后 commit
    routing = {**{b: d["routed"].get(b, []) for b in
                  ["世界观", "人物", "卡章纲", "立项卡", "违禁词", "文风参考"]}}
    routing["世界观"] = routing["世界观"] + ["随手记.md"]
    r2 = c.post("/api/project/import/commit",
                json={"folder": str(src), "name": "陈的书", "parent": str(tmp_path / "书库"),
                      "routing": routing})
    assert r2.status_code == 200
    d2 = r2.json()
    # 返回体顶层就是 project_state(同 create_project 形状对齐)+ summary 键,不套 state/ok 包装
    assert d2["title"] == "陈的书"
    assert d2["summary"]["placed"]["世界观"] == 2
    assert (tmp_path / "书库" / "陈的书" / "外置大脑/人物/主角.md").exists()

    # 不存在的 folder → 400
    assert c.post("/api/project/import/scan", json={"folder": str(tmp_path / "没这个")}).status_code == 400


def test_import_dir_bucket_transcodes_gbk_and_book_loads(tmp_path):
    from loom import importer
    from loom.paths import WORLD_DIR_REL
    from loom.studio import names
    src = tmp_path / "s"; src.mkdir()
    (src / "力量体系.md").write_bytes("# 力量体系\n\n凡境→筑基。".encode("gbk"))   # GBK 硬设定文件
    routing = {"世界观": ["力量体系.md"], "人物": [], "卡章纲": [], "立项卡": [], "违禁词": [], "文风参考": []}
    root = importer.import_folder(src, "GBK硬设定书", routing, tmp_path / "lib")
    # 落盘成 UTF-8、可读、字符不变
    assert (root / WORLD_DIR_REL / "力量体系.md").read_text(encoding="utf-8").count("凡境") == 1
    # 下游严 utf-8 读侧不崩(旗舰场景:studio.names + import_summary)
    assert names(root)["sections"]                        # 力量体系命中硬设定小节,不崩
    assert importer.import_summary(root, routing)["placed"]["世界观"] == 1   # 不 UnicodeDecodeError


def test_import_single_bucket_preserves_indent_and_blanks(tmp_path):
    from loom import importer
    from loom.paths import CARD_REL
    src = tmp_path / "s"; src.mkdir()
    (src / "总纲.md").write_text("　第一卷:复仇。\n\n　第二卷:夺宝。\n", encoding="utf-8")  # 全角缩进+空行
    routing = {"世界观": [], "人物": [], "卡章纲": ["总纲.md"], "立项卡": [], "违禁词": [], "文风参考": []}
    root = importer.import_folder(src, "缩进书", routing, tmp_path / "lib")
    card = (root / CARD_REL).read_text(encoding="utf-8")
    assert "　第一卷" in card and "　第二卷" in card     # 全角缩进原样,不被 strip 吃掉


def test_route_outline_synonyms_to_card(tmp_path):
    from loom.importer import route_files
    r = route_files(["总纲.md", "细纲.md", "纲要.md", "提纲.md"])
    assert set(r["卡章纲"]) == {"总纲.md", "细纲.md", "纲要.md", "提纲.md"} and r["unknown"] == []


def test_route_chapter_files_to_body():
    from loom import importer
    routed = importer.route_files(["第1章.md", "第二章.txt", "05.txt", "世界观设定.md", "乱七八糟.md"])
    assert set(routed["正文"]) == {"第1章.md", "第二章.txt", "05.txt"}   # 章号/纯序号→正文
    assert routed["世界观"] == ["世界观设定.md"]                         # 关键词桶不变
    assert "乱七八糟.md" in routed["unknown"]                            # 猜不中仍 unknown


def test_txt_only_routes_to_body_not_setting_buckets():
    from loom import importer
    routed = importer.route_files(["人物小传.txt"])   # .txt 命中人物关键词,但 txt 只准进正文
    assert "人物小传.txt" not in routed["人物"]
    assert "人物小传.txt" in routed["unknown"]        # 非正文的 txt → unknown(设定桶 md-only)


def test_buckets_includes_body():
    from loom import importer
    assert "正文" in importer.BUCKETS

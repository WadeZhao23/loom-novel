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

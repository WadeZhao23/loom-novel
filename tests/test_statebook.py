"""状态账本:跨章状态单一真相——write-once/存活快照/删章摘除/重编号搬运(除虫闭环 §1)。"""
from loom import statebook
from loom.paths import STATEBOOK_REL


def _book(project):
    return (project / STATEBOOK_REL).read_text(encoding="utf-8")


def test_append_creates_file_with_template_header(project):
    ok = statebook.append_section(project, 2, [
        "- [物品] 远古药胚:已吞服消耗(冲刷绝脉) | 证据:「张口将其吞入腹中」",
        "- [规则] 因果锁定:满100%触发,100%反馈 | 证据:「因果锁定」",
    ])
    assert ok is True
    text = _book(project)
    assert "## 第2章" in text and "远古药胚" in text
    assert text.startswith("# 状态账本")   # 首次落盘带模板头


def test_write_once_per_section(project):
    statebook.append_section(project, 2, ["- [物品] 药胚:消耗 | 证据:「x」"])
    assert statebook.append_section(project, 2, ["- [物品] 别的:获得 | 证据:「y」"]) is False
    assert "别的" not in _book(project)     # 已有节绝不动(人写优先)


def test_append_empty_lines_is_noop(project):
    before = _book(project)                     # scaffold 已铺模板头,文件本就存在
    assert statebook.append_section(project, 3, []) is False
    assert _book(project) == before             # 空 lines 一个字节都不动


def test_parse_book_tolerant(project):
    statebook.append_section(project, 1, ["- [物品] 铁剑:获得 | 证据:「拾起铁剑」", "随手写的杂行不解析"])
    book = statebook.parse_book(_book(project))
    assert book[1] == [("物品", "铁剑:获得 | 证据:「拾起铁剑」")]


def test_snapshot_survival_rules(project):
    # 第1章:消耗物品行+规则行+状态行;第2..10章:各一条状态行(把第1章挤出滚动窗)
    statebook.append_section(project, 1, [
        "- [物品] 远古药胚:已吞服消耗 | 证据:「吞入腹中」",
        "- [物品] 铁剑:获得 | 证据:「拾起」",
        "- [规则] 因果锁定:100%反馈 | 证据:「锁定」",
        "- [状态] 江澈:炼气三层 | 证据:「三层」",
    ])
    for n in range(2, 11):
        statebook.append_section(project, n, [f"- [状态] 江澈:炼气{n}层 | 证据:「第{n}」"])
    snap = statebook.snapshot_for(project, 10)
    assert "远古药胚" in snap and "因果锁定" in snap      # 消耗物品行+规则行永不折(防复活/防漂移)
    assert "铁剑" not in snap                             # 远章非消耗物品行丢弃
    assert "炼气三层" not in snap and "炼气10层" in snap  # 状态行只留滚动窗(近8章)
    assert snap.splitlines()[0].startswith("- 第")        # 每行带章号溯源


def test_snapshot_empty_book_is_empty(project):
    assert statebook.snapshot_for(project, 5) == ""


def test_strip_and_remap(project):
    statebook.append_section(project, 1, ["- [物品] A:获得 | 证据:「a」"])
    statebook.append_section(project, 2, ["- [物品] B:消耗 | 证据:「b」"])
    statebook.append_section(project, 3, ["- [物品] C:获得 | 证据:「c」"])
    removed = statebook.strip_section(project, 2)
    assert "B:消耗" in removed and "## 第2章" not in _book(project)
    statebook.remap_keys(project, {3: 2})                 # 两段式防互换
    assert "## 第2章" in _book(project) and "C:获得" in _book(project)


def test_fresh_template_not_substantive(project):
    # 模板头全是注释/占位括注:不进任何 prompt(占位过滤口径,一期立的规矩)
    from loom.parse import is_substantive
    from loom.scaffold import TEMPLATES_DIR
    text = (TEMPLATES_DIR / "外置大脑/状态账本.md").read_text(encoding="utf-8")
    assert is_substantive(text) is False


def test_delete_chapter_strips_statebook_with_trash(project):
    from loom import chapters
    from loom.fsutil import atomic_write_text
    for n in (1, 2, 3):
        atomic_write_text(project / f"正文/第{n}章.md", f"# 第{n}章\n\n正文{n}。")
        statebook.append_section(project, n, [f"- [物品] 宝物{n}:获得 | 证据:「{n}」"])
    chapters.delete_chapter(project, 2)
    text = _book(project)
    assert "宝物2" not in text
    assert "宝物3" in text and "## 第2章" in text     # 第3章顺延成第2章,账本键跟着搬
    trash = list((project / "正文/.回收站").glob("第2章-*"))
    assert trash and any("状态账本" in f.name for f in trash[0].rglob("*.md"))   # 留底在回收站的外置大脑/子目录里

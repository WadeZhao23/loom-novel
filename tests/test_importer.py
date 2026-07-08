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

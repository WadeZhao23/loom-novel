"""章号排序键:导入正文按真实章序重排,不被文件名字符串序(第1/第10/第2)坑。"""
from loom.cnnum import cn_to_int, chapter_order_key


def test_cn_to_int_basic():
    assert cn_to_int("一") == 1
    assert cn_to_int("十") == 10
    assert cn_to_int("十一") == 11
    assert cn_to_int("二十") == 20
    assert cn_to_int("三十五") == 35
    assert cn_to_int("一百") == 100
    assert cn_to_int("一百零一") == 101
    assert cn_to_int("两百") == 200
    assert cn_to_int("零") == 0
    assert cn_to_int("不是数字") is None


def test_chapter_order_key_arabic_sorts_numerically():
    files = ["第10章.md", "第2章.md", "第1章.md"]
    assert sorted(files, key=chapter_order_key) == ["第1章.md", "第2章.md", "第10章.md"]


def test_chapter_order_key_chinese():
    files = ["第十章.txt", "第二章.txt", "第一章.txt"]
    assert sorted(files, key=chapter_order_key) == ["第一章.txt", "第二章.txt", "第十章.txt"]


def test_chapter_order_key_pure_serial():
    files = ["10.txt", "2.txt", "1.txt"]
    assert sorted(files, key=chapter_order_key) == ["1.txt", "2.txt", "10.txt"]


def test_chapter_order_key_unparsable_last_stable():
    files = ["随便.md", "第1章.md", "楔子.md"]
    out = sorted(files, key=chapter_order_key)
    assert out[0] == "第1章.md"                    # 有章号的排前
    assert out[1:] == ["楔子.md", "随便.md"]         # 抽不到的按名稳定兜底

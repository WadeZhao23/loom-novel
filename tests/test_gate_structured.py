"""S2 Gate 结果结构化:Issue 的 category/severity/paragraph_index + parse_verdict 的扩展字段解析。"""
import pytest

from loom.gates import Issue
from loom.parse import parse_verdict


class TestIssueStructured:
    """Issue dataclass 结构化字段测试。"""

    def test_default_fields(self):
        """向后兼容:只有 kind/desc/evidence 时,category=kind,severity=0,paragraph_index=None。"""
        i = Issue(kind="OOC", desc="主角不像本人", evidence="他笑了")
        assert i.category == "OOC"
        assert i.severity == 0
        assert i.paragraph_index is None
        assert i.kind == "OOC"
        assert i.desc == "主角不像本人"
        assert i.evidence == "他笑了"

    def test_explicit_category(self):
        """category 可独立指定,不与 kind 绑定。"""
        i = Issue(kind="人物OOC", desc="主角不像本人", category="人物")
        assert i.category == "人物"
        assert i.kind == "人物OOC"

    def test_severity_range(self):
        """severity 保持原值,不校验范围(调用方负责)。"""
        i = Issue(kind="漂移", desc="错了", severity=3)
        assert i.severity == 3

    def test_paragraph_index(self):
        """paragraph_index 可为 int 或 None。"""
        i1 = Issue(kind="漂移", desc="错了", paragraph_index=2)
        assert i1.paragraph_index == 2
        i2 = Issue(kind="漂移", desc="错了", paragraph_index=None)
        assert i2.paragraph_index is None

    def test_as_dict_includes_structured_fields(self):
        """as_dict() 包含新字段,category 和 severity 总有;paragraph_index 只在非 None 时出现。"""
        i = Issue(kind="OOC", desc="问题", evidence="引", category="人物", severity=4, paragraph_index=2)
        d = i.as_dict()
        assert d["category"] == "人物"
        assert d["severity"] == 4
        assert d["paragraph_index"] == 2
        assert d["类别"] == "OOC"
        assert d["问题"] == "问题"
        assert d["证据"] == "引"

    def test_as_dict_omits_paragraph_index_when_none(self):
        """paragraph_index 为 None 时 as_dict 不输出该键(前端契约兼容)。"""
        i = Issue(kind="OOC", desc="问题", severity=3)
        d = i.as_dict()
        assert "paragraph_index" not in d
        assert d["severity"] == 3
        assert d["category"] == "OOC"


class TestParseVerdictExtended:
    """parse_verdict 对扩展字段 S/P 的解析。"""

    def test_backward_compat_no_extras(self):
        """老格式(无 S/P)解析正常,结构化字段有合理默认值。"""
        issues = parse_verdict("- 设定漂移 | 力量体系错了 | 证据:\"凡境写成蜕凡\"")
        assert len(issues) == 1
        i = issues[0]
        assert i.kind == "设定漂移"
        assert i.severity == 0
        assert i.paragraph_index is None
        assert i.category == "设定漂移"

    def test_parse_severity(self):
        """S:3 正确解析严重度。"""
        issues = parse_verdict("- 人物OOC | 主角不说话 | 证据:\"他沉默\" | S:3")
        assert len(issues) == 1
        assert issues[0].severity == 3
        assert issues[0].paragraph_index is None

    def test_parse_severity_and_paragraph(self):
        """S:4 | P:2 同时解析。"""
        issues = parse_verdict("- 断钩子 | 没接上章末 | 证据:\"新的开始\" | S:4 | P:2")
        assert len(issues) == 1
        assert issues[0].severity == 4
        assert issues[0].paragraph_index == 2

    def test_parse_severity_chinese_colon(self):
        """S：5 (中文冒号)也能解析。"""
        issues = parse_verdict("- 设定漂移 | 境界错了 | 证据:\"筑基\" | S：5")
        assert len(issues) == 1
        assert issues[0].severity == 5

    def test_parse_severity_out_of_range_clamped(self):
        """S:0 和 S:6 超出 1-5 范围 → 保持 0。"""
        low = parse_verdict("- 漂移 | 错了 | 证据:\"x\" | S:0")
        high = parse_verdict("- 漂移 | 错了 | 证据:\"x\" | S:6")
        assert low[0].severity == 0
        assert high[0].severity == 0

    def test_parse_invalid_extra_ignored(self):
        """不认识的扩展字段忽略,不影响解析。"""
        issues = parse_verdict("- 漂移 | 错了 | 证据:\"x\" | X:foo | S:2")
        assert len(issues) == 1
        assert issues[0].severity == 2
        assert issues[0].paragraph_index is None

    def test_multiple_issues_mixed(self):
        """多条硬伤,有的带扩展字段有的不带。"""
        raw = (
            "- 设定漂移 | 力量体系错了 | 证据:\"凡境\" | S:5\n"
            "- 人物OOC | 主角不开口 | 证据:\"沉默\" | S:3 | P:1\n"
            "- 断钩子 | 没接住 | 证据:\"新章\"\n"
        )
        issues = parse_verdict(raw)
        assert len(issues) == 3
        assert issues[0].severity == 5
        assert issues[0].paragraph_index is None
        assert issues[1].severity == 3
        assert issues[1].paragraph_index == 1
        assert issues[2].severity == 0
        assert issues[2].paragraph_index is None

    def test_pass_phrase_returns_empty(self):
        """'通过'等无硬伤返回空。"""
        assert parse_verdict("通过") == []
        assert parse_verdict("无硬伤") == []
        assert parse_verdict("- 通过") == []

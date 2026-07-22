"""测试 M5:Gate 结果 UI 可视化——_enrich_issues / 事件增强 / 端点。"""
from __future__ import annotations

from loom import events
from loom.gates import Issue, _enrich_issues, _derive_suggestion, _split_paragraphs


class TestEnrichIssues:
    def test_derive_suggestion_from_desc(self):
        """从问题描述派生建议。"""
        s = _derive_suggestion("人物OOC:主角表现得不像自己")
        assert "建议" in s or "修正" in s

    def test_derive_suggestion_empty(self):
        """空描述返回空建议。"""
        assert _derive_suggestion("") == ""

    def test_enrich_with_paragraph_index(self):
        """有 paragraph_index 时提取对应段落原文。"""
        text = "第一段\n\n第二段有问题的内容\n\n第三段"
        issues = [Issue(kind="设定漂移", desc="境界名不对",
                        evidence="第二段",
                        paragraph_index=1)]
        details = _enrich_issues(issues, text)
        assert len(details) == 1
        d = details[0]
        assert d["category"] == "设定漂移"
        assert "第二段" in d["original_text"]
        assert d["paragraph_index"] == 1

    def test_enrich_without_paragraph_index_uses_evidence(self):
        """没有 paragraph_index 时用 evidence 文本定位。"""
        text = "前面一些内容\n\n问题文本在这里\n\n后面一些内容"
        issues = [Issue(kind="OOC", desc="角色OOC",
                        evidence="问题文本在这里",
                        paragraph_index=None)]
        details = _enrich_issues(issues, text)
        assert len(details) == 1
        d = details[0]
        assert d["original_text"]  # 应该包含 evidence
        assert "问题文本" in d["original_text"]

    def test_enrich_always_has_suggestion(self):
        """每条 issue 都有 suggestion 字段。"""
        text = "第一段\n\n第二段"
        issues = [Issue(kind="逻辑不通", desc="时间线冲突",
                        evidence="第二段", paragraph_index=1)]
        details = _enrich_issues(issues, text)
        assert details[0]["suggestion"]

    def test_enrich_empty_issues(self):
        """空 issues 列表返回空列表。"""
        assert _enrich_issues([], "some text") == []

    def test_enrich_empty_text(self):
        """空原文返回空 original_text 但有 suggestion。"""
        issues = [Issue(kind="OOC", desc="角色OOC", evidence="")]
        details = _enrich_issues(issues, "")
        assert len(details) == 1
        assert details[0]["original_text"] == ""  # 空文本无原文

    def test_enrich_multi_issues(self):
        """多条 issue 都正确处理。"""
        text = "第零段\n\n第一段问题\n\n第二段问题\n\n第三段"
        issues = [
            Issue(kind="类型A", desc="问题1", paragraph_index=1),
            Issue(kind="类型B", desc="问题2", paragraph_index=2),
        ]
        details = _enrich_issues(issues, text)
        assert len(details) == 2
        assert "第一段" in details[0]["original_text"]
        assert "第二段" in details[1]["original_text"]

    def test_severity_preserved(self):
        """严重度正确传递。"""
        issues = [Issue(kind="OOC", desc="OOC", severity=5)]
        details = _enrich_issues(issues, "text")
        assert details[0]["severity"] == 5


class TestIssueDataclass:
    def test_original_text_field(self):
        """Issue 支持 original_text 字段。"""
        i = Issue(kind="测试", desc="测试", original_text="原文内容")
        assert i.original_text == "原文内容"

    def test_suggestion_field(self):
        """Issue 支持 suggestion 字段。"""
        i = Issue(kind="测试", desc="测试", suggestion="建议内容")
        assert i.suggestion == "建议内容"

    def test_as_dict_includes_new_fields(self):
        """as_dict 包含 original_text 和 suggestion（仅在有值时）。"""
        i = Issue(kind="测试", desc="测试", original_text="原文",
                  suggestion="建议")
        d = i.as_dict()
        assert d["original_text"] == "原文"
        assert d["suggestion"] == "建议"

    def test_as_dict_excludes_empty_fields(self):
        """as_dict 不含空的 original_text/suggestion。"""
        i = Issue(kind="测试", desc="测试")
        d = i.as_dict()
        assert "original_text" not in d
        assert "suggestion" not in d

    def test_category_defaults_to_kind(self):
        """category 默认取 kind 值。"""
        i = Issue(kind="设定漂移", desc="测试")
        assert i.category == "设定漂移"


class TestGateIssuesEvent:
    def test_event_without_detail(self):
        """gate_issues 事件不传 issues_detail 时无此键。"""
        ev = events.gate_issues("质检", "编辑", 1, [{"类别": "测试", "问题": "test"}])
        assert ev["type"] == "gate_issues"
        assert "issues_detail" not in ev

    def test_event_with_detail(self):
        """gate_issues 传 issues_detail 时包含此键。"""
        detail = [{"category": "设定漂移", "severity": 3, "original_text": "原文",
                    "suggestion": "建议"}]
        ev = events.gate_issues("质检", "编辑", 1,
                                [{"类别": "测试", "问题": "test"}],
                                issues_detail=detail)
        assert ev["type"] == "gate_issues"
        assert ev["issues_detail"] == detail

    def test_event_contract_preserved(self):
        """既有字段不变:label/role/round/issues。"""
        detail = [{"category": "测试", "severity": 1}]
        ev = events.gate_issues("质检", "编辑", 1,
                                [{"类别": "测试", "问题": "test"}],
                                issues_detail=detail)
        assert ev["label"] == "质检"
        assert ev["role"] == "编辑"
        assert ev["round"] == 1
        assert ev["issues"] == [{"类别": "测试", "问题": "test"}]


class TestSplitParagraphs:
    def test_empty_text(self):
        assert _split_paragraphs("") == []

    def test_one_paragraph(self):
        assert _split_paragraphs("一段正文") == ["一段正文"]

    def test_multi_paragraphs(self):
        result = _split_paragraphs("一段\n\n二段\n\n三段")
        assert result == ["一段", "二段", "三段"]

    def test_trim_whitespace(self):
        result = _split_paragraphs("  一段  \n\n  二段  ")
        assert result == ["一段", "二段"]

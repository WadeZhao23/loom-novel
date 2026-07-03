"""并发写同一文件不互相拆台:tmp 名唯一(pid+序号),谁后 replace 谁生效。

回归背景:tmp 名曾只带 pid,同进程两次并发 atomic_write_text 同一路径会共用
一个 tmp——先完成的把 tmp 替换走,后一个 os.replace 抛 FileNotFoundError,
表现为「自动保存失败: 500」(自动保存 debounce 撞上 learn 前的显式落盘)。
"""
from __future__ import annotations

import threading

from loom.fsutil import atomic_write_text


def test_concurrent_writes_same_path_no_error(tmp_path):
    target = tmp_path / "第1章.md"
    payloads = [f"版本{i}\n" + "正文" * 50 for i in range(8)]
    errors: list[BaseException] = []

    def w(text: str) -> None:
        try:
            for _ in range(20):
                atomic_write_text(target, text)
        except BaseException as e:  # noqa: BLE001 - 测试要捕获一切
            errors.append(e)

    threads = [threading.Thread(target=w, args=(p,)) for p in payloads]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"并发写抛错:{errors[:3]}"
    content = target.read_text(encoding="utf-8")
    assert content in payloads, "终态必须是某一次完整写入,不能是半截/混合"
    # 不留 tmp 残骸
    assert not list(tmp_path.glob(".*.tmp.*")), "并发写后不应残留 tmp 文件"

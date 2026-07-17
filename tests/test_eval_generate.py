"""Generation suite:evalapi 生成接缝 + 固定输入生成链路。零真实模型。"""
from loom import evalapi

_GEN_SEAM = ("run_pipeline", "scaffold_init", "load_config", "save_config",
             "Config", "get_backend", "outline_path")


def test_evalapi_generation_seam_exports():
    # Phase 1 生成接缝:七个再导出必须存在且进 __all__(evals 只准走门面)
    for name in _GEN_SEAM:
        assert hasattr(evalapi, name), f"evalapi 缺生成接缝导出:{name}"
        assert name in evalapi.__all__, f"{name} 未进 evalapi.__all__"

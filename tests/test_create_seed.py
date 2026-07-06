"""建书前置输入:一句话设定进 loom.toml(AI 铺底稿用),平台进立项卡平台行(违禁词基线用)。"""
from loom.config import Config, load_config, save_config
from loom.scaffold import init as scaffold_init


def test_idea_survives_default_backend_inheritance(tmp_path, monkeypatch):
    # 用户存过全局默认后端时,apply_default_to_new_book 整写 loom.toml——idea 不许被冲掉
    from loom import userconf
    home = tmp_path / "loom_home"
    monkeypatch.setenv("LOOM_HOME", str(home))
    root = scaffold_init("默认后端书", parent=tmp_path, idea="重生成崇祯")
    cfg = load_config(root)
    userconf.save_default_backend(cfg.provider, cfg.model, cfg.base_url)   # 先存一份用户级默认
    userconf.apply_default_to_new_book(root)
    assert load_config(root).idea == "重生成崇祯"


def test_idea_and_platform_land(tmp_path):
    root = scaffold_init("崇祯书", parent=tmp_path, idea='重生成崇祯,开局"砍"魏忠贤', platform="番茄")
    assert load_config(root).idea == "重生成崇祯,开局'砍'魏忠贤"   # 双引号净化成单引号,守 toml 单行字符串
    card = (root / "外置大脑/立项卡.md").read_text(encoding="utf-8")
    assert "平台:番茄" in card and "平台:起点" not in card


def test_defaults_untouched(tmp_path):
    root = scaffold_init("素书", parent=tmp_path)
    assert load_config(root).idea == ""
    assert "平台:起点" in (root / "外置大脑/立项卡.md").read_text(encoding="utf-8")


def test_idea_survives_save_config_roundtrip(tmp_path):
    root = scaffold_init("留存书", parent=tmp_path, idea="一句话设定")
    cfg = load_config(root)
    save_config(root, cfg)                       # 设置页保存后端会整写 toml,idea 不许被冲掉
    assert load_config(root).idea == "一句话设定"
    cfg2 = load_config(scaffold_init("空书", parent=tmp_path))
    save_config(tmp_path / "空书", cfg2)
    assert "idea" not in (tmp_path / "空书" / "loom.toml").read_text(encoding="utf-8")  # 没填就不写行,toml 干净

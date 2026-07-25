import re
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_local_markdown_links_resolve():
    missing = []
    documents = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
    for document in documents:
        text = document.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", text):
            if target.startswith(("http://", "https://", "#")):
                continue
            clean = target.split("#", 1)[0]
            if clean and not (document.parent / clean).resolve().exists():
                missing.append(f"{document.relative_to(ROOT)} -> {target}")
    assert missing == []


def test_current_layout_matches_gas_import_state():
    layout = (ROOT / "docs/current-layout.md").read_text(encoding="utf-8")
    assert "gas_queue_importer.py" in layout
    assert "ローカル取込、trigger配備は未完了" not in layout


def test_historical_reviews_point_to_current_status() -> None:
    architecture = (
        ROOT / "docs/reviews/system-architecture-review-20260725.md"
    ).read_text(encoding="utf-8")
    operations = (
        ROOT / "docs/reviews/operations-security-review-20260725.md"
    ).read_text(encoding="utf-8")

    for review in (architecture, operations):
        assert "## 後続実装注記" in review
        assert "full-system-review-20260725.md" in review
    assert "solar_self_consumption_opportunity.py" in architecture
    assert "shadow_execution.py" in architecture


def test_current_layout_does_not_present_fixtures_as_runtime() -> None:
    layout = (ROOT / "docs/current-layout.md").read_text(encoding="utf-8")

    assert "判断・実行の試作" in layout
    assert "未配備の機器Adapter" in layout
    assert "fixture限定" in layout
    assert "本番運用や自動化の完成とみなさない" in layout

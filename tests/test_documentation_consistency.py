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

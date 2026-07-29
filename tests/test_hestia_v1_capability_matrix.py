from pathlib import Path


DOCUMENT = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "release"
    / "hestia-v1-capability-matrix.md"
)


def test_capability_matrix_exists_and_lists_all_current_integrations() -> None:
    content = DOCUMENT.read_text(encoding="utf-8")

    assert "# HESTIA v1 能力・適格性・配備マトリクス" in content
    for integration in (
        "FusionSolar / SmartLogger",
        "SwitchBot",
        "Smart LEDZ Base",
        "EcoCute / ECHONET Lite",
        "Qrio Lock",
        "Miele@home",
        "BRAVIA",
        "日産サクラ",
        "WAREMA WMS",
        "MTRL-RK-901SI",
        "Eufy 天候・映像補助",
        "北陸電力料金情報",
    ):
        assert integration in content


def test_capability_matrix_defines_the_required_evidence_boundaries() -> None:
    content = DOCUMENT.read_text(encoding="utf-8")

    for status in (
        "`implemented`",
        "`fixture_only`",
        "`reader_only`",
        "`shadow_only`",
        "`live_qualified`",
        "`deployed`",
        "`deferred`",
    ):
        assert status in content

    assert "コード、匿名 fixture、単体テストだけでは `live_qualified` または `deployed` にしません" in content
    assert "実機の単発、短時間、24 時間の read-only 記録" in content
    assert "実機の読取結果、IP、機器 ID、認証値、Raw 本文はこの文書へ記載しません" in content

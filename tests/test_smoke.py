from create_pywire_app.main import LOGO


def test_logo_exists():
    assert "System" in LOGO or "Web Framework" in LOGO or "cyan" in LOGO

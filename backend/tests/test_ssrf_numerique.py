"""#451 : écritures numériques abrégées d'une adresse locale (`127.1`, `2130706433`, `0x7f.0.0.1`) refusées comme `127.0.0.1`."""
import pytest

from app.isospec import check_url


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/x", "http://127.1/x", "http://2130706433/x", "http://0x7f.0.0.1/x", "http://0177.0.0.1/x",
    "http://0/x", "http://169.254.169.254/x", "http://2852039166/x", "http://[::1]/x", "http://999.1.1.1/x",
])
def test_adresses_locales_refusees(url):
    with pytest.raises(ValueError):
        check_url(url)


@pytest.mark.parametrize("url", [
    "http://10.0.0.5/x", "http://192.168.1.5:8080/hook", "http://1.2.3.4/x", "https://example.org/a.iso", "https://hooks.example.org/t",
])
def test_adresses_legitimes_acceptees(url):
    assert check_url(url) == url

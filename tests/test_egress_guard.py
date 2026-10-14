# Nume fictive ("Acme Rail") — numele real al clientului nu intră în repo.
import pytest

from research_gateway.egress_guard import EgressBlocked, EgressGuard, load

PRICE = r"(?i)\bpre[țt](ul|uri|urile)?\s+(de\s+)?achizi[țt]i[ea]\b"


@pytest.fixture
def guard():
    return EgressGuard(["Acme Rail", "Proiect Delta", "ZT9"], [PRICE])


@pytest.mark.parametrize("text", [
    "Acme Rail",
    "oferta pentru ACME RAIL",
    "acme rail",
    "Ăcme Râil",                      # diacritice
    "A.C.M.E-Rail",                   # separatori
    "a c m e r a i l",
    "Acm3 R4il",                      # leetspeak
    "q=Acme%20Rail+bogie",            # percent-encoding
    "https://x.com/?q=acme+rail",
    "proiect delta",
    "piesa pentru ZT9",
    "prețul de achiziție este 120 EUR",
    "pret achizitie",
])
def test_blocks(guard, text):
    with pytest.raises(EgressBlocked):
        guard.check(text)


@pytest.mark.parametrize("text", [
    "bogie frame 3EST000123 datasheet",
    "EN 15085 welding certification supplier",
    "AZT9X",                          # termen scurt: doar cuvânt întreg
    "preț de listă 45 EUR",
])
def test_allows(guard, text):
    assert guard.check(text) == text


def test_nested_payload_including_keys(guard):
    with pytest.raises(EgressBlocked):
        guard.check({"q": "bogie", "meta": [{"note": "pt Acme Rail"}]})
    with pytest.raises(EgressBlocked):
        guard.check({"Acme Rail": "x"})


def test_error_never_echoes_sensitive_text(guard):
    with pytest.raises(EgressBlocked) as e:
        guard.check("Acme Rail")
    assert "acme" not in str(e.value).lower()
    assert e.value.rules == ["term#0"]


@pytest.mark.parametrize("terms", [[], ["", "  "], ["<NUME_CLIENT>"]])
def test_fail_closed_on_bad_denylist(terms):
    with pytest.raises(ValueError):
        EgressGuard(terms)


def test_example_denylist_refuses_to_load():
    with pytest.raises(ValueError):
        load("config/denylist.example.yaml")


def test_load_from_yaml(tmp_path):
    p = tmp_path / "d.yaml"
    p.write_text(f"terms: [Acme Rail]\npatterns: ['{PRICE}']\n", encoding="utf-8")
    g = load(str(p))
    with pytest.raises(EgressBlocked):
        g.check("pret de achizitie")

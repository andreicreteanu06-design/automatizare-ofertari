import json

import pytest
from fastapi.testclient import TestClient

from research_gateway.app import create_app, public_http
from research_gateway.egress_guard import EgressGuard

CODE = "3EST000123"
GOOD = "https://distribuitor.example/p/1"


def ld(obj):
    return f'<script type="application/ld+json">{json.dumps(obj)}</script>'


PAGE = (ld({"@type": "Product", "sku": CODE, "offers": {"price": "1200", "priceCurrency": "EUR"}})
        + f"<table><tr><td>{CODE}</td><td>1.250,00 €</td></tr></table>")
INNER = f"{CODE}\t1.250,00 €"


class Fakes:
    def __init__(self, urls=(GOOD,), pages=None, score=0.97):
        self.urls, self.pages, self.score = list(urls), pages or {GOOD: (PAGE, INNER)}, score
        self.searched, self.fetched, self.verified = [], [], []

    async def search(self, q):
        self.searched.append(q)
        return self.urls

    async def fetch(self, url):
        self.fetched.append(url)
        page = self.pages[url]
        if isinstance(page, Exception):
            raise page
        return page

    async def verify(self, code, text):
        self.verified.append(text)
        if isinstance(self.score, Exception):
            raise self.score
        return self.score


def client(f):
    guard = EgressGuard(["Acme Rail"])
    return TestClient(create_app(guard, f.search, f.fetch, f.verify, threshold=0.9))


def post(f, **body):
    return client(f).post("/research", json={"code": CODE, **body})


def test_blocked_query_never_leaves():
    f = Fakes()
    r = post(f, query="bogie pentru Acme Rail")
    assert r.status_code == 403
    assert r.json()["detail"] == {"blocked": ["term#0"]}
    assert "acme" not in r.text.lower()
    assert f.searched == [] and f.fetched == []


def test_happy_path_verified():
    f = Fakes()
    body = post(f).json()
    assert f.searched == [CODE]  # fără query explicit se caută codul
    assert [(r["source"], r["price"], r["currency"], r["status"]) for r in body["results"]] == [
        ("jsonld", "1200", "EUR", "verified"), ("text", "1250.00", "EUR", "verified")]
    assert body["results"][0]["laya_score"] == 0.97
    assert CODE in f.verified[0]


def test_unsafe_and_blocked_urls_are_skipped():
    f = Fakes(urls=["http://192.168.1.1/admin", "file:///etc/passwd", "http://localhost:8080/",
                    "http://router.local/", "https://shop.example/acme-rail/3EST000123", GOOD, GOOD])
    body = post(f).json()
    assert f.fetched == [GOOD]
    assert body["blocked_urls"] == 1
    assert "acme" not in json.dumps(body).lower()


@pytest.mark.parametrize("score,status", [(0.5, "unverified"), (0.9, "verified")])
def test_laya_threshold(score, status):
    body = post(Fakes(score=score)).json()
    assert {r["status"] for r in body["results"]} == {status}


def test_laya_down_means_unverified():
    body = post(Fakes(score=ConnectionError("laya down"))).json()
    assert {r["status"] for r in body["results"]} == {"unverified"}
    assert body["errors"][0]["error"].startswith("laya: ConnectionError")


def test_code_only_in_jsonld_skips_laya_and_stays_unverified():
    page = ld({"@type": "Product", "sku": CODE, "offers": {"price": 5, "priceCurrency": "EUR"}}) + "<p>Alt produs</p>"
    f = Fakes(pages={GOOD: (page, "Alt produs")})
    (row,) = post(f).json()["results"]
    assert (row["status"], row["code_on_page"], row["laya_score"]) == ("unverified", None, None)
    assert f.verified == []


def test_inner_text_hides_css_hidden_code():
    """innerText (CSS randat) are prioritate: codul ascuns prin CSS extern nu e pe pagină."""
    page = f'<p class="ascuns-din-css">{CODE} 10 €</p><p>Alt produs</p>'
    f = Fakes(pages={GOOD: (page, "Alt produs")})
    assert post(f).json()["results"] == []


def test_inner_text_tabs_do_not_join_cells():
    f = Fakes(pages={GOOD: ("<p>x</p>", "3EST000\t123\t10 €")})
    assert post(f).json()["results"] == []


def test_failing_page_does_not_stop_others():
    other = "https://alt.example/p"
    f = Fakes(urls=[other, GOOD], pages={other: TimeoutError("navigare"), GOOD: (PAGE, INNER)})
    body = post(f).json()
    assert body["errors"] == [{"url": other, "error": "TimeoutError: navigare"}]
    assert len(body["results"]) == 2


def test_max_pages():
    urls = [f"https://s{i}.example/p" for i in range(8)]
    f = Fakes(urls=urls, pages={u: ("<p>nimic</p>", "nimic") for u in urls})
    post(f, max_pages=3)
    assert f.fetched == urls[:3]


@pytest.mark.parametrize("body", [{"code": "x"}, {"code": CODE, "max_pages": 50}, {"code": CODE, "query": "q" * 201}])
def test_input_validation(body):
    assert client(Fakes()).post("/research", json=body).status_code == 422


def test_create_app_fails_closed_without_denylist(monkeypatch):
    monkeypatch.delenv("DENYLIST_PATH", raising=False)
    with pytest.raises(KeyError):
        create_app()


@pytest.mark.parametrize("url,ok", [
    ("https://shop.example/p", True), ("http://8.8.8.8/", True),
    ("http://10.0.0.5/", False), ("http://172.20.0.3/", False), ("http://127.0.0.1/", False),
    ("http://[::1]/", False), ("http://169.254.169.254/latest", False),
    ("ftp://shop.example/", False), ("javascript:alert(1)", False),
    ("http://localhost/", False), ("http://printer.local/", False),
])
def test_public_http(url, ok):
    assert public_http(url) is ok

import json
from decimal import Decimal

import pytest

from research_gateway.extract import (code_on_page, extract, find_code, find_prices, jsonld_products,
                                      labeled_codes, parse_number, visible_text)

CODE = "3EST000123"


def ld(obj):
    return f'<script type="application/ld+json">{json.dumps(obj)}</script>'


# --- Curățare HTML ----------------------------------------------------------------

@pytest.mark.parametrize("hidden", [
    f"<script>var sku='{CODE}';</script>",
    f"<style>.x::after{{content:'{CODE}'}}</style>",
    f"<!-- {CODE} -->",
    f"<noscript>{CODE}</noscript>",
    f"<template><p>{CODE}</p></template>",
    f"<title>{CODE}</title>",
    f'<div style="display:none">{CODE}</div>',
    f'<div style="color:red; visibility: hidden">{CODE}</div>',
    f'<span style="opacity:0">{CODE}</span>',
    f'<span style="font-size:0px;">{CODE}</span>',
    f"<div hidden>{CODE}</div>",
    f'<div aria-hidden="true">{CODE}</div>',
    f'<p class="price d-none">{CODE}</p>',
    f'<span class="sr-only">{CODE}</span>',
    f'<div style="display:none"><p><b>{CODE}</b></p></div>',   # copiii elementelor ascunse
    f'<input type="hidden" value="{CODE}">',
    ld({"@type": "Product", "sku": CODE}),
])
def test_hidden_content_is_removed(hidden):
    text = visible_text(f"<html><body><p>Bogie frame</p>{hidden}<p>EN 15085</p></body></html>")
    assert CODE not in text
    assert "Bogie frame" in text and "EN 15085" in text


def test_visible_survives_around_hidden():
    html = f'<div>Cod: <span style="display:none">FAKE999</span><b>{CODE}</b></div>'
    assert visible_text(html) == f"Cod: {CODE}"


def test_opacity_nonzero_is_visible():
    assert CODE in visible_text(f'<span style="opacity:0.5">{CODE}</span>')


def test_body_visible_without_closing_head():
    assert CODE in visible_text(f"<html><head><title>x</title><body><p>{CODE}</p>")


def test_malformed_html_unclosed_and_orphan_tags():
    html = f"<div><p>unu<p>doi</span></div><p>{CODE}"
    assert visible_text(html) == f"unu\ndoi\n{CODE}"


def test_entities_and_whitespace():
    assert visible_text("<p>A&nbsp;&amp;\n\t  B</p>") == "A & B"


# --- Coduri -----------------------------------------------------------------------

def test_code_exact_case_insensitive():
    assert code_on_page(f"Art. {CODE.lower()} stoc", CODE) == "exact"


@pytest.mark.parametrize("page", ["3EST 000 123", "3EST-000-123", "3est.000.123", "3EST/000123"])
def test_code_normalized_separators(page):
    assert code_on_page(f"Cod {page} disponibil", CODE) == "normalized"


def test_code_given_with_separators_matches_compact_page():
    assert code_on_page(f"Cod {CODE}", "3EST-000-123") == "normalized"
    assert code_on_page("Cod 3EST-000-123", "3EST-000-123") == "exact"


def test_code_split_by_inline_tags_is_exact():
    assert code_on_page(visible_text("<p><b>3EST</b>000<i>123</i></p>"), CODE) == "exact"


def test_code_not_joined_across_table_cells():
    text = visible_text("<table><tr><td>3EST000</td><td>123</td></tr></table>")
    assert code_on_page(text, CODE) is None


@pytest.mark.parametrize("page", [f"X{CODE}", f"{CODE}4", f"{CODE}A", "3EST00012"])
def test_code_boundaries(page):
    assert code_on_page(f"cod {page} aici", CODE) is None


def test_find_code_positions():
    text = f"{CODE} si {CODE}"
    assert [(s, e) for s, e, _ in find_code(text, CODE)] == [(0, 10), (14, 24)]


def test_empty_code_rejected():
    with pytest.raises(ValueError):
        code_on_page("x", " - ")


def test_labeled_codes():
    text = ("SKU: AB-1234\nPart No. 3EST000123\nCod produs: 7781/22\n"
            "Art.-Nr. 55X10\nReferinta 9988\nCod postal fara cifre\nRefund policy")
    assert labeled_codes(text) == ["AB-1234", "3EST000123", "7781/22", "55X10", "9988"]


# --- Prețuri ----------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("1234", "1234"), ("1234.5", "1234.5"), ("12,50", "12.50"),
    ("1.234,56", "1234.56"), ("1,234.56", "1234.56"), ("1 234,56", "1234.56"),
    ("1'234.56", "1234.56"), ("1.234", "1234"), ("1,234", "1234"),
    ("1.234.567", "1234567"), ("1.234.567,89", "1234567.89"),
])
def test_parse_number(raw, expected):
    assert parse_number(raw) == Decimal(expected)


@pytest.mark.parametrize("text,price,cur", [
    ("Pret: 1.234,56 €", "1234.56", "EUR"),
    ("€1,234.56", "1234.56", "EUR"),
    ("EUR 99", "99", "EUR"),
    ("99,90 eur/buc", "99.90", "EUR"),
    ("$ 15.20", "15.20", "USD"),
    ("US$15", "15", "USD"),
    ("450 lei", "450", "RON"),
    ("1 250,00 RON", "1250.00", "RON"),
    ("£12.5", "12.5", "GBP"),
    ("CHF 1'234.50", "1234.50", "CHF"),
    ("120 zł", "120", "PLN"),
    ("Pret : 1 234,56 €", "1234.56", "EUR"),
])
def test_find_prices(text, price, cur):
    prices = find_prices(visible_text(f"<p>{text}</p>"))
    assert [(p, c) for _, _, p, c in prices] == [(Decimal(price), cur)]


@pytest.mark.parametrize("text", ["Stoc: 25 buc", "Cod 3EST000123", "Livrare in 5 zile", "EURO5 standard"])
def test_no_price_without_currency(text):
    assert find_prices(text) == []


# --- JSON-LD ----------------------------------------------------------------------

def test_jsonld_product_offer():
    html = ld({"@context": "https://schema.org", "@type": "Product", "name": "Bogie frame",
               "sku": CODE, "mpn": "MPN-1",
               "offers": {"@type": "Offer", "price": "1234.50", "priceCurrency": "EUR"}})
    assert jsonld_products(html) == [
        {"codes": {CODE, "MPN-1"}, "name": "Bogie frame", "prices": [(Decimal("1234.50"), "EUR")]}]


def test_jsonld_graph_aggregate_offer_list_and_spec():
    html = ld({"@graph": [
        {"@type": "WebPage", "name": "x"},
        {"@type": ["Product", "Thing"], "sku": "A1",
         "offers": {"@type": "AggregateOffer", "lowPrice": 10, "priceCurrency": "usd"}},
        {"@type": "http://schema.org/Product", "gtin13": "5901234123457",
         "offers": [{"price": 5, "priceCurrency": "EUR"},
                    {"priceSpecification": {"price": 7.5, "priceCurrency": "RON"}}]},
    ]})
    products = jsonld_products(html)
    assert [p["prices"] for p in products] == [
        [(Decimal("10"), "USD")],
        [(Decimal("5"), "EUR"), (Decimal("7.5"), "RON")]]


def test_jsonld_invalid_and_codeless_skipped():
    html = ('<script type="application/ld+json">{"@type": "Product", "sku": "A1",}</script>'
            + ld({"@type": "Product", "name": "fara cod",
                  "offers": {"price": 1, "priceCurrency": "EUR"}})
            + ld({"@type": "Product", "sku": "B2"}))
    assert jsonld_products(html) == [{"codes": {"B2"}, "name": None, "prices": []}]


def test_jsonld_offer_without_currency_ignored():
    assert jsonld_products(ld({"@type": "Product", "sku": "A1", "offers": {"price": 9}}))[0]["prices"] == []


# --- extract() --------------------------------------------------------------------

def test_extract_jsonld_and_text():
    html = (ld({"@type": "Product", "sku": "3EST-000-123", "name": "Bogie",
                "offers": {"price": "1200", "priceCurrency": "EUR"}})
            + f"<table><tr><td>{CODE}</td><td>1.250,00 €</td></tr></table>")
    hits = extract(html, CODE, url="https://distribuitor.example/p/1")
    assert [(h.source, h.price, h.currency, h.code_on_page) for h in hits] == [
        ("jsonld", Decimal("1200"), "EUR", "exact"),
        ("text", Decimal("1250.00"), "EUR", "exact")]
    assert all(h.url == "https://distribuitor.example/p/1" for h in hits)
    assert CODE in hits[1].context and "1.250,00" in hits[1].context


def test_extract_code_only_in_jsonld_is_not_on_page():
    """Cloaking: codul există doar în date structurate -> rămâne Neverificat."""
    html = ld({"@type": "Product", "sku": CODE, "offers": {"price": 1, "priceCurrency": "EUR"}})
    assert [h.code_on_page for h in extract(html + "<p>Alt produs</p>", CODE)] == [None]


def test_extract_ignores_code_and_price_in_hidden_elements():
    html = (f'<div style="display:none">{CODE} 10 €</div>'
            f"<script>price='{CODE} 20 EUR'</script><p>Alt produs 30 €</p>")
    assert extract(html, CODE) == []


def test_extract_orders_text_prices_by_distance_and_respects_window():
    filler = "x" * 400
    html = f"<p>99 € {filler}</p><p>Pret vechi 15 € ; cod {CODE} pret 12 €</p>"
    hits = extract(html, CODE)
    assert [h.price for h in hits] == [Decimal("12"), Decimal("15")]


def test_extract_price_assigned_to_nearest_code_occurrence():
    html = f"<p>{CODE} 10 €</p><p>{'y' * 200}</p><p>{CODE.replace('000', ' 000 ')} </p>"
    (hit,) = extract(html, CODE)
    assert hit.code_on_page == "exact"

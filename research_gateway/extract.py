"""Extragere deterministă de coduri și prețuri din pagini de distribuitori.

Fără LLM. Două surse, ambele marcate cu proveniența lor:
  - JSON-LD (schema.org Product/Offer) — structurat, dar poate conține date care
    NU apar pe pagină, deci nu dovedește singur prezența codului;
  - textul VIZIBIL al paginii, după eliminarea scripturilor, stilurilor,
    comentariilor și elementelor ascunse — singura bază pentru `code_on_page`.

Orice rezultat rămâne „Neverificat” până îl confirmă Laya.
"""
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

# --- HTML -> text vizibil -------------------------------------------------------

# Nu "head": fără </head> explicit, html.parser ar ascunde tot body-ul.
_SKIP_TAGS = {"script", "style", "noscript", "template", "title", "iframe", "object", "svg"}
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
              "source", "track", "wbr"}
_BLOCK_TAGS = {"address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
               "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4",
               "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "option", "p", "pre",
               "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul"}
_HIDDEN_STYLE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(?:\.0+)?\s*(?:;|$)"
    r"|font-size\s*:\s*0(?:px|em|rem|%)?\s*(?:;|$)", re.I)
_HIDDEN_CLASSES = {"hidden", "d-none", "sr-only", "visually-hidden", "invisible"}


def _is_hidden(tag, attrs):
    a = dict(attrs)
    return (tag in _SKIP_TAGS
            or "hidden" in a
            or (a.get("aria-hidden") or "").lower() == "true"
            or bool(_HIDDEN_STYLE.search(a.get("style") or ""))
            or not _HIDDEN_CLASSES.isdisjoint((a.get("class") or "").split()))


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []      # (tag, hidden) pentru elementele deschise, non-void
        self.hidden = 0      # câte elemente ascunse sunt deschise acum
        self.text = []
        self.jsonld = []
        self._in_jsonld = False

    def handle_starttag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self.text.append("\n")
        if tag in _VOID_TAGS:
            return
        hidden = _is_hidden(tag, attrs)
        self.stack.append((tag, hidden))
        self.hidden += hidden
        if tag == "script" and (dict(attrs).get("type") or "").lower() == "application/ld+json":
            self._in_jsonld = True
            self.jsonld.append("")

    def handle_startendtag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self.text.append("\n")

    def handle_endtag(self, tag):
        if tag in _BLOCK_TAGS:
            self.text.append("\n")
        if not any(t == tag for t, _ in self.stack):
            return  # tag de închidere orfan: HTML stricat, îl ignorăm
        while self.stack:  # închide implicit și elementele rămase deschise (<p>, <li>)
            t, hidden = self.stack.pop()
            self.hidden -= hidden
            if t == tag:
                break
        if tag == "script":
            self._in_jsonld = False

    def handle_data(self, data):
        if self._in_jsonld:
            self.jsonld[-1] += data
        elif not self.hidden:
            # Ca browserul: whitespace-ul din sursă e un spațiu; \n vine doar din tag-uri bloc.
            # shortcut: <pre> nu e tratat separat — rar pe paginile de produs.
            self.text.append(re.sub(r"[ \t\r\n\f\v]+", " ", data))
    # Comentariile (<!-- -->) ajung în handle_comment, care nu face nimic: dispar.


def _parse(html):
    p = _Parser()
    p.feed(html)
    p.close()
    return p


def _clean_text(chunks):
    text = "".join(chunks).replace(" ", " ").replace(" ", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r" *\n[\n ]*", "\n", text).strip()


def visible_text(html):
    """Textul pe care îl vede un om: fără script/style/comentarii/elemente ascunse.
    shortcut: ascunderea prin clase CSS din foi externe nu e detectabilă din HTML —
    pentru siguranță deplină, dă-i lui visible_text innerText-ul randat de Playwright."""
    return _clean_text(_parse(html).text)


def page_text(html, inner_text=None):
    """Textul de analizat: innerText-ul randat de Playwright dacă îl avem (respectă și
    CSS-ul extern), altfel visible_text(html). innerText separă celulele cu TAB -> rând nou."""
    if inner_text is None:
        return visible_text(html)
    return _clean_text([inner_text.replace("\t", "\n")])


# --- Coduri ---------------------------------------------------------------------

_SEP = r"[ ./\-]?"  # fără \n/\t: un cod nu continuă dintr-o celulă/paragraf în altul
_LABELED_CODE = re.compile(
    r"(?:\bSKU|\bMPN|\bEAN|\bGTIN|\bPart\s*(?:No|Number|#)|\bP/N|\bArt(?:icle|ikel)?[\s.-]*(?:No|Nr)"
    r"|\bRef(?:erin[țt]a|erence)?|\bCod(?:ul)?(?:\s+(?:produs|articol|piesă|piesa))?)\.?\s*[:#]?\s*"
    r"([A-Z0-9](?:[A-Z0-9./-]{1,38}[A-Z0-9])?)", re.I)


def _strip_code(code):
    return re.sub(r"[\s./\-]", "", code)


def _code_regex(code):
    chars = _strip_code(code)
    if not chars:
        raise ValueError("cod gol")
    body = _SEP.join(re.escape(c) for c in chars)
    return re.compile(r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])", re.I)


def find_code(text, code):
    """Pozițiile codului în text, cu tipul potrivirii: 'exact' (identic, ignorând
    majusculele) sau 'normalized' (diferă doar prin separatori: spațiu . / -)."""
    exact = code.strip().casefold()
    return [(m.start(), m.end(), "exact" if m.group(0).casefold() == exact else "normalized")
            for m in _code_regex(code).finditer(text)]


def code_on_page(text, code):
    """'exact' > 'normalized' > None. None => rândul rămâne „Neverificat”."""
    kinds = {kind for _, _, kind in find_code(text, code)}
    return "exact" if "exact" in kinds else ("normalized" if kinds else None)


def labeled_codes(text):
    """Coduri precedate de o etichetă (SKU:, Part No., Cod produs:, Art.-Nr.)."""
    return [m.group(1) for m in _LABELED_CODE.finditer(text) if re.search(r"\d", m.group(1))]


# --- Prețuri --------------------------------------------------------------------

_CURRENCIES = {"€": "EUR", "eur": "EUR", "euro": "EUR", "$": "USD", "us$": "USD", "usd": "USD",
               "£": "GBP", "gbp": "GBP", "lei": "RON", "ron": "RON", "chf": "CHF",
               "pln": "PLN", "zł": "PLN"}
_CUR = r"(?:US\$|€|\$|£|zł|\b(?:EUR|EURO|USD|GBP|RON|LEI|CHF|PLN)\b)"
# shortcut: "Stoc 2 100,00 EUR" se citește 2100 (spațiul e și separator de mii);
# ambiguitate inerentă textului — de aceea JSON-LD are prioritate în extract().
_NUM = r"(?<![\d.,])(?:\d{1,3}(?:[ .,']\d{3})+|\d+)(?:[.,]\d{1,2})?(?![\d])"
_PRICE = re.compile(rf"(?P<c1>{_CUR})\s?(?P<n1>{_NUM})|(?P<n2>{_NUM})\s?(?P<c2>{_CUR})", re.I)


def parse_number(s):
    """'1.234,56' / '1,234.56' / '1 234,56' / "1'234.56" -> Decimal('1234.56').
    Un singur separator urmat de exact 3 cifre = separator de mii ('1.234' -> 1234)."""
    s = re.sub(r"[ ']", "", s)
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if dec == "," else ",", "").replace(dec, ".")
    elif "," in s or "." in s:
        sep = "," if "," in s else "."
        whole, *rest = s.split(sep)
        s = f"{whole}.{rest[0]}" if len(rest) == 1 and len(rest[0]) in (1, 2) else s.replace(sep, "")
    return Decimal(s)


def find_prices(text):
    """[(start, end, Decimal, 'EUR')] pentru fiecare sumă cu monedă explicită.
    Sumele fără monedă sunt ignorate intenționat: nu ghicim moneda."""
    out = []
    for m in _PRICE.finditer(text):
        num, cur = (m["n1"], m["c1"]) if m["n1"] else (m["n2"], m["c2"])
        out.append((m.start(), m.end(), parse_number(num), _CURRENCIES[cur.casefold()]))
    return out


# --- JSON-LD --------------------------------------------------------------------

_CODE_KEYS = ("sku", "mpn", "productID", "gtin", "gtin8", "gtin12", "gtin13", "gtin14")


def _nodes(obj):
    if isinstance(obj, list):
        for x in obj:
            yield from _nodes(x)
    elif isinstance(obj, dict):
        yield obj
        for k in ("@graph", "hasVariant", "itemListElement", "item"):
            if k in obj:
                yield from _nodes(obj[k])


def _types(node):
    t = node.get("@type", [])
    return {x.split("/")[-1] for x in ([t] if isinstance(t, str) else t)}


def _decimal(v):
    try:
        return Decimal(str(v).strip())
    except (InvalidOperation, ValueError):
        return None


def _offer_prices(offers):
    for o in offers if isinstance(offers, list) else [offers]:
        if not isinstance(o, dict):
            continue
        specs = o.get("priceSpecification") or []
        for src in [o, *(specs if isinstance(specs, list) else [specs])]:
            price = _decimal(src.get("price", src.get("lowPrice")))
            cur = src.get("priceCurrency") or o.get("priceCurrency")
            if price is not None and cur:
                yield price, str(cur).upper()
                break


def jsonld_products(html):
    """Produsele din <script type="application/ld+json">: coduri, nume, prețuri.
    Blocurile JSON invalide sunt ignorate (nu ghicim reparații)."""
    products = []
    for raw in _parse(html).jsonld:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for node in _nodes(data):
            if "Product" not in _types(node):
                continue
            codes = {str(node[k]).strip() for k in _CODE_KEYS if node.get(k)}
            prices = list(_offer_prices(node.get("offers") or []))
            if codes:
                products.append({"codes": codes, "name": node.get("name"), "prices": prices})
    return products


# --- Punct de intrare -----------------------------------------------------------

PRICE_WINDOW = 300  # caractere în jurul codului în care un preț e considerat al lui


@dataclass(frozen=True)
class PriceHit:
    code: str
    price: Decimal
    currency: str
    source: str              # "jsonld" | "text"
    code_on_page: str | None  # "exact" | "normalized" | None (=> Neverificat)
    context: str             # fragment din text, pentru afișare și pentru Laya
    url: str | None = None


def extract(html, code, url=None, inner_text=None):
    """Toate prețurile asociate codului căutat: întâi JSON-LD, apoi text după distanță."""
    text = page_text(html, inner_text)
    on_page = code_on_page(text, code)
    target = _strip_code(code).casefold()
    hits = []

    for p in jsonld_products(html):
        if any(_strip_code(c).casefold() == target for c in p["codes"]):
            hits += [PriceHit(code, price, cur, "jsonld", on_page, p["name"] or "", url)
                     for price, cur in p["prices"]]

    best = {}  # (start preț) -> (distanță, PriceHit)
    code_spans = find_code(text, code)
    for ps, pe, price, cur in find_prices(text):
        for cs, ce, kind in code_spans:
            dist = max(cs - pe, ps - ce, 0)
            if dist <= PRICE_WINDOW and dist < best.get(ps, (PRICE_WINDOW + 1,))[0]:
                ctx = text[max(0, min(cs, ps) - 40):max(ce, pe) + 40].strip()
                best[ps] = (dist, PriceHit(code, price, cur, "text", kind, ctx, url))
    hits += [h for _, h in sorted(best.values(), key=lambda dh: dh[0])]
    return hits

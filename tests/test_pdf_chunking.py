"""Chunking pe DoclingDocument construit manual — aceeași structură pe care o produce
Docling din PDF, fără să rulăm modelele (torch) în teste."""
import re

import pytest
from docling_core.types.doc import (BoundingBox, DocItemLabel, DoclingDocument, ProvenanceItem, Size, TableCell,
                                    TableData)

from app.ingest.pdf import DocMeta, chunk_document, context_header, doc_id_for

META = DocMeta("FT-suport", "Feroparts SRL", "Knorr-Bremse", "Fișă tehnică")
HEADER = re.compile(r"^\[Furnizor: [^|\]]+ \| Producător: [^|\]]+ \| Doc: [^|\]]+ \| Pagina \d+(-\d+)?\]$")


def prov(page):
    return ProvenanceItem(page_no=page, bbox=BoundingBox(l=0, t=0, r=1, b=1), charspan=(0, 1))


def new_doc(pages=3):
    doc = DoclingDocument(name="t")
    for p in range(1, pages + 1):
        doc.add_page(page_no=p, size=Size(width=595, height=842))
    return doc


def add_table(doc, rows, page, caption=None):
    cells = [TableCell(text=v, start_row_offset_idx=r, end_row_offset_idx=r + 1,
                       start_col_offset_idx=c, end_col_offset_idx=c + 1, column_header=r == 0)
             for r, row in enumerate(rows) for c, v in enumerate(row)]
    cap = doc.add_text(label=DocItemLabel.CAPTION, text=caption, prov=prov(page)) if caption else None
    return doc.add_table(data=TableData(num_rows=len(rows), num_cols=len(rows[0]), table_cells=cells),
                         caption=cap, prov=prov(page))


def text(doc, s, page):
    doc.add_text(label=DocItemLabel.TEXT, text=s, prov=prov(page))


# --- Antetul de context -----------------------------------------------------------

def test_header_exact_format():
    assert context_header(META, 4, 4) == \
        "[Furnizor: Feroparts SRL | Producător: Knorr-Bremse | Doc: Fișă tehnică | Pagina 4]"
    assert context_header(META, 3, 4).endswith("| Pagina 3-4]")


def test_header_sanitizes_and_defaults():
    meta = DocMeta("x", "A | B]  SRL", "", "Cert\nISO")
    assert context_header(meta, 1, 1) == "[Furnizor: A / B) SRL | Producător: necunoscut | Doc: Cert ISO | Pagina 1]"


def test_every_chunk_starts_with_header():
    doc = new_doc()
    doc.add_title(text="Suport boghiu", prov=prov(1))
    text(doc, "Introducere.", 1)
    add_table(doc, [["Cod", "Masa"], ["3EST000123", "12 kg"]], 2)
    text(doc, "Note.", 3)
    chunks = chunk_document(doc, META)
    assert len(chunks) == 3
    for c in chunks:
        first = c.text.splitlines()[0]
        assert HEADER.match(first), first
        assert first.endswith(f"Pagina {c.page_start}]")
    assert [c.index for c in chunks] == [0, 1, 2]


# --- Tabele: niciodată tăiate -----------------------------------------------------

def test_huge_table_is_one_chunk():
    rows = [["Cod", "Descriere", "Masa"]] + [[f"P{i:04d}", "x" * 40, f"{i} kg"] for i in range(300)]
    doc = new_doc()
    text(doc, "Inainte.", 1)
    add_table(doc, rows, 1)
    text(doc, "Dupa.", 1)
    tables = [c for c in chunk_document(doc, META, max_chars=500) if c.kind == "table"]
    assert len(tables) == 1
    assert len(tables[0].text) > 10 * 500
    assert all(f"P{i:04d}" in tables[0].text for i in range(300))


def test_table_caption_once_and_not_as_separate_text():
    doc = new_doc()
    add_table(doc, [["Cod", "Masa"], ["A1", "1 kg"]], 1, caption="Tabel 2: Mase")
    chunks = chunk_document(doc, META)
    assert len(chunks) == 1
    assert chunks[0].text.count("Tabel 2: Mase") == 1


def test_table_continued_with_repeated_header_is_merged():
    doc = new_doc()
    add_table(doc, [["Cod", "Masa"], ["A1", "1 kg"], ["A2", "2 kg"]], 2, caption="Tabel 1")
    add_table(doc, [["Cod", "Masa"], ["A3", "3 kg"]], 3)
    (c,) = chunk_document(doc, META)
    assert (c.kind, c.page_start, c.page_end) == ("table", 2, 3)
    assert c.text.splitlines()[0].endswith("| Pagina 2-3]")
    assert c.text.count("| Cod") == 1  # antetul repetat nu se dublează
    assert re.search(r"A1.*\n.*A2.*\n.*A3", c.text)


def test_table_without_matching_header_is_not_guessed_as_continuation():
    doc = new_doc()
    add_table(doc, [["Cod", "Masa"], ["A1", "1 kg"]], 1)
    add_table(doc, [["A2", "2 kg"], ["A3", "3 kg"]], 2)  # continuare fără antet
    chunks = chunk_document(doc, META)
    assert len(chunks) == 2
    assert chunks[0].page_end == 1 and chunks[1].page_start == 2


@pytest.mark.parametrize("second,between,page", [
    ([["Cod", "Lungime"], ["A2", "2 mm"]], None, 2),      # aceleași coloane, altă proprietate
    ([["X", "Y", "Z"], ["1", "2", "3"]], None, 2),        # alt număr de coloane
    ([["Cod", "Masa"], ["A2", "2 kg"]], "Text intre", 2),  # text între ele
    ([["Cod", "Masa"], ["A2", "2 kg"]], None, 3),          # pagină sărită
    ([["Cod", "Masa"], ["A2", "2 kg"]], None, 1),          # aceeași pagină: tabele distincte
])
def test_tables_not_merged(second, between, page):
    doc = new_doc()
    add_table(doc, [["Cod", "Masa"], ["A1", "1 kg"]], 1)
    if between:
        text(doc, between, page)
    add_table(doc, second, page)
    assert sum(c.kind == "table" for c in chunk_document(doc, META)) == 2


# --- Text -------------------------------------------------------------------------

def test_text_grouped_up_to_max_chars():
    doc = new_doc()
    for i in range(10):
        text(doc, f"Paragraf {i} " + "a" * 80, 1)
    chunks = chunk_document(doc, META, max_chars=300)
    assert len(chunks) > 1
    body = lambda c: c.text.split("\n", 1)[1]
    assert all(len(body(c)) <= 300 for c in chunks)
    assert "".join(body(c) for c in chunks).count("Paragraf") == 10


def test_text_never_crosses_pages():
    doc = new_doc()
    text(doc, "Pe pagina 1.", 1)
    text(doc, "Pe pagina 2.", 2)
    assert [(c.page_start, c.page_end) for c in chunk_document(doc, META)] == [(1, 1), (2, 2)]


def test_long_paragraph_stays_whole():
    doc = new_doc()
    text(doc, "b" * 5000, 1)
    (c,) = chunk_document(doc, META, max_chars=500)
    assert "b" * 5000 in c.text


def test_section_heading_in_chunks_and_splits_sections():
    doc = new_doc()
    doc.add_heading(text="Caracteristici", prov=prov(1))
    text(doc, "Otel S355.", 1)
    add_table(doc, [["Cod", "Masa"], ["A1", "1 kg"]], 1)
    doc.add_heading(text="Montaj", prov=prov(1))
    text(doc, "Cuplu 80 Nm.", 1)
    chunks = chunk_document(doc, META)
    assert [(c.kind, c.section) for c in chunks] == [
        ("text", "Caracteristici"), ("table", "Caracteristici"), ("text", "Montaj")]
    assert chunks[2].text.splitlines()[1] == "## Montaj"


def test_page_headers_footers_skipped():
    doc = new_doc()
    doc.add_text(label=DocItemLabel.PAGE_HEADER, text="CONFIDENTIAL - antet", prov=prov(1))
    text(doc, "Continut.", 1)
    doc.add_text(label=DocItemLabel.PAGE_FOOTER, text="Pagina 1 din 3", prov=prov(1))
    (c,) = chunk_document(doc, META)
    assert "antet" not in c.text and "din 3" not in c.text


def test_empty_document():
    assert chunk_document(new_doc(), META) == []


@pytest.mark.parametrize("path,expected", [
    ("data/FT Suport boghiu (rev.2).pdf", "FT-Suport-boghiu-rev-2"),
    ("x/ăîș.pdf", "doc"),
])
def test_doc_id(path, expected):
    assert doc_id_for(path) == expected

"""PDF-uri tehnice -> chunk-uri pentru RAG (Docling).

Reguli de chunking:
  - un tabel = un chunk, ÎNTREG, oricât de mare: nu se taie niciodată;
  - un tabel continuat pe pagina următoare (imediat după, aceleași antete)
    e lipit de primul — Docling le detectează ca două tabele separate;
  - textul se grupează pe secțiuni până la MAX_CHARS, fără să treacă peste o pagină
    (ca citarea [doc_id:pagina] să fie exactă);
  - fiecare chunk începe cu antetul de context:
      [Furnizor: <Nume> | Producător: <Mfr> | Doc: <Tip> | Pagina <Nr>]
"""
import argparse
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from docling_core.types.doc import DocItemLabel, SectionHeaderItem, TableItem, TextItem, TitleItem

MAX_CHARS = 1500  # ~400 tokeni de text; tabelele sunt exceptate
_SKIP_LABELS = {DocItemLabel.CAPTION, DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER}


@dataclass(frozen=True)
class DocMeta:
    doc_id: str
    supplier: str
    manufacturer: str
    doc_type: str
    source_revision: str | None = None


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    index: int
    kind: str              # "text" | "table"
    page_start: int
    page_end: int
    section: str | None
    text: str              # cu antet: exact ce se embed-uiește și ce primește LLM-ul


def _field(value):
    # "|" și "]" ar strica formatul antetului.
    return re.sub(r"\s+", " ", (value or "").replace("|", "/").replace("]", ")")).strip() or "necunoscut"


def context_header(meta, page_start, page_end):
    pages = str(page_start) if page_start == page_end else f"{page_start}-{page_end}"
    return (f"[Furnizor: {_field(meta.supplier)} | Producător: {_field(meta.manufacturer)}"
            f" | Doc: {_field(meta.doc_type)} | Pagina {pages}]")


def _cells(md_line):
    return [c.strip() for c in md_line.strip().strip("|").split("|")]


def _merge_tables(first_md, next_md):
    """Lipește rândurile tabelului de continuare. Dacă repetă antetul, îl sare;
    dacă nu are antet, primul lui „antet” markdown e de fapt un rând de date."""
    header = next(line for line in first_md.splitlines() if line.lstrip().startswith("|"))
    lines = [line for line in next_md.splitlines() if line.lstrip().startswith("|")]  # fără legendă
    rows = lines[2:] if _cells(lines[0]) == _cells(header) else [lines[0], *lines[2:]]
    return first_md + "\n" + "\n".join(rows)


def chunk_document(doc, meta, max_chars=MAX_CHARS):
    blocks = []      # dict-uri mutabile, transformate în Chunk la final
    section = None
    page = 1
    for item, _ in doc.iterate_items():
        pages = [p.page_no for p in getattr(item, "prov", [])] or [page]
        page = pages[0]
        if isinstance(item, TableItem):
            md = item.export_to_markdown(doc=doc).strip()  # include deja legenda (caption)
            if "|" not in md:
                continue
            prev = blocks[-1] if blocks else None
            if (prev and prev["kind"] == "table" and prev["ncols"] == item.data.num_cols
                    and min(pages) == prev["p1"] + 1
                    and _cells(next(x for x in prev["body"].splitlines() if x.lstrip().startswith('|')))
                    == _cells(next(x for x in md.splitlines() if x.lstrip().startswith('|')))):
                prev["body"] = _merge_tables(prev["body"], md)
                prev["p1"] = max(pages)
                continue
            blocks.append({"kind": "table", "p0": min(pages), "p1": max(pages), "section": section,
                           "body": md, "ncols": item.data.num_cols})
        elif isinstance(item, (SectionHeaderItem, TitleItem)):
            section = item.text.strip() or section
        elif isinstance(item, TextItem) and item.label not in _SKIP_LABELS and item.text.strip():
            text = item.text.strip()
            prev = blocks[-1] if blocks else None
            if (prev and prev["kind"] == "text" and prev["section"] == section and prev["p0"] == page
                    and len(prev["body"]) + 1 + len(text) <= max_chars):
                prev["body"] += "\n" + text
            else:  # un paragraf mai lung decât max_chars rămâne întreg, într-un chunk propriu
                blocks.append({"kind": "text", "p0": page, "p1": page, "section": section, "body": text})

    chunks = []
    for i, b in enumerate(blocks):
        parts = [context_header(meta, b["p0"], b["p1"])]
        if b["section"]:
            parts.append(f"## {b['section']}")
        parts.append(b["body"])
        chunks.append(Chunk(meta.doc_id, i, b["kind"], b["p0"], b["p1"], b["section"], "\n".join(parts)))
    return chunks


def convert_pdf(path, ocr=False):
    """PDF -> DoclingDocument. TableFormer ACCURATE + potrivire pe celulele PDF-ului:
    structura tabelelor tehnice contează mai mult decât viteza.
    Rulează offline: modelele vin din DOCLING_ARTIFACTS_PATH (vezi serviciul model-fetch)."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions(do_ocr=ocr, do_table_structure=True,
                              artifacts_path=os.environ.get("DOCLING_ARTIFACTS_PATH"))
    opts.table_structure_options.mode = TableFormerMode.ACCURATE
    opts.table_structure_options.do_cell_matching = True
    converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
    return converter.convert(str(path)).document


def doc_id_for(path):
    """ID lizibil pentru citări: [FT-suport-boghiu:3]."""
    return re.sub(r"[^A-Za-z0-9_-]+", "-", Path(path).stem).strip("-")[:60] or "doc"


def main(argv=None):
    p = argparse.ArgumentParser(description="Indexează un PDF tehnic în Qdrant.")
    p.add_argument("pdf")
    p.add_argument("--supplier", required=True)
    p.add_argument("--manufacturer", default="")
    p.add_argument("--doc-type", required=True, help='ex. "Fișă tehnică", "Certificat ISO", "Manual"')
    p.add_argument("--ocr", action="store_true", help="pentru PDF-uri scanate")
    a = p.parse_args(argv)

    from app.rag.index import BgeM3, index_chunks, qdrant_client
    meta = DocMeta(doc_id_for(a.pdf), a.supplier, a.manufacturer, a.doc_type, hashlib.sha256(Path(a.pdf).read_bytes()).hexdigest())
    chunks = chunk_document(convert_pdf(a.pdf, a.ocr), meta)
    if not chunks:
        raise ValueError('PDF fără text/tabele extrase. Verifică documentul și reîncearcă folosind --ocr pentru scanări.')
    index_chunks(qdrant_client(), BgeM3(), chunks, meta)
    tables = sum(c.kind == "table" for c in chunks)
    print(f"{meta.doc_id}: {len(chunks)} chunk-uri ({tables} tabele) indexate")


if __name__ == "__main__":
    main()

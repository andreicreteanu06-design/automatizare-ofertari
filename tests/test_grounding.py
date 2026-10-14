import pytest

from app.rag.grounding import NOT_FOUND, REMOVED, ground, is_part_code

FRAGS = [
    {"doc_id": "FT-suport", "page": 3, "page_end": 4,
     "text": "[Furnizor: F | Producător: K | Doc: Fișă tehnică | Pagina 3-4]\n| Cod | Masa |\n| 3EST000123 | 12 kg |"},
    {"doc_id": "FACT-FDX-1", "page": 1, "page_end": 1,
     "text": "Cod furnizor: DIN933-M12X40; Preț unitar net: 1.4 EUR; GTIN 5901234123457"},
    {"doc_id": "CERT-iso", "page": 1, "page_end": 1, "text": "Certificat ISO/TS 22163, material S355J2"},
]


def test_keeps_code_present_in_cited_fragment():
    g = ground("Suportul 3EST000123 are 12 kg [FT-suport:3].", FRAGS)
    assert g.answer == "Suportul 3EST000123 are 12 kg [FT-suport:3]."
    assert g.removed_codes == [] and g.citations == [("FT-suport", 3)] and g.grounded


def test_separator_variants_still_match():
    g = ground("Codul 3EST-000-123 [FT-suport:3]. Șurubul DIN933 M12X40 [FACT-FDX-1:1].", FRAGS)
    assert g.removed_codes == []


def test_removes_hallucinated_code():
    g = ground("Alternativa este 3EST000999 [FT-suport:3].", FRAGS)
    assert g.answer == f"Alternativa este {REMOVED} [FT-suport:3]."
    assert g.removed_codes == ["3EST000999"]


def test_code_must_be_in_fragment_cited_in_same_sentence():
    # Codul există în FT-suport, dar propoziția citează doar factura.
    g = ground("Piesa 3EST000123 costă 1.4 EUR [FACT-FDX-1:1].", FRAGS)
    assert g.removed_codes == ["3EST000123"]


def test_sentence_without_citation_cannot_carry_codes():
    g = ground("Masa e 12 kg [FT-suport:3]. Folosiți și 3EST000123 pentru montaj.", FRAGS)
    assert g.answer.endswith(f"Folosiți și {REMOVED} pentru montaj.")


def test_each_list_line_is_checked_separately():
    answer = "Piese:\n- 3EST000123 [FT-suport:3]\n- DIN933-M12X40 [FT-suport:3]"
    g = ground(answer, FRAGS)
    assert g.removed_codes == ["DIN933-M12X40"]
    assert "- 3EST000123 [FT-suport:3]\n- " + REMOVED in g.answer


def test_partial_code_is_not_grounded_by_longer_code():
    assert ground("Varianta EST000 [FT-suport:3].", FRAGS).removed_codes == ["EST000"]


def test_invalid_citations_removed():
    g = ground("Masa e 12 kg [FT-suport:3] [INVENTAT:9] [FT-suport:7].", FRAGS)
    assert g.answer == "Masa e 12 kg [FT-suport:3]."
    assert g.removed_citations == ["[INVENTAT:9]", "[FT-suport:7]"]


def test_page_inside_chunk_range_is_valid():
    g = ground("Tabelul continuă cu 3EST000123 [FT-suport:4].", FRAGS)
    assert g.citations == [("FT-suport", 4)] and g.removed_codes == []


def test_citation_after_period_belongs_to_sentence():
    g = ground("Codul este 3EST000123. [FT-suport:3]", FRAGS)
    assert g.removed_codes == []


def test_citation_ids_are_not_treated_as_codes():
    g = ground("Vezi [FACT-FDX-1:1] și [FT-suport:3].", FRAGS)
    assert g.removed_codes == [] and len(g.citations) == 2


def test_non_codes_untouched():
    text = "Livrat pe 2026-09-15, preț 549.00 EUR, conform EN 15085 și ISO 22163, anul 2026 [FACT-FDX-1:1]."
    assert ground(text, FRAGS).answer == text


def test_material_grade_and_gtin_are_checked():
    g = ground("Material S355J2 [CERT-iso:1]. GTIN 5901234123457 [FACT-FDX-1:1]. Alt GTIN 4006381333931 [FACT-FDX-1:1].", FRAGS)
    assert g.removed_codes == ["4006381333931"]


def test_think_block_stripped():
    g = ground("<think>poate 3EST000999?</think>\nCodul 3EST000123 [FT-suport:3].", FRAGS)
    assert g.answer == "Codul 3EST000123 [FT-suport:3]."


def test_not_found_is_grounded_without_citations():
    assert ground(NOT_FOUND, FRAGS).grounded
    assert not ground("Piesa e bună.", FRAGS).grounded


@pytest.mark.parametrize("token,expected", [
    ("3EST000123", True), ("M12X40", True), ("S355", True), ("5901234123457", True),
    ("2026", False), ("2026-09-15", False), ("549.00", False), ("15085", False), ("FT-suport", False), ("M12", False),
])
def test_is_part_code(token, expected):
    assert is_part_code(token) is expected

from app.rag.corrections import applicable, excluded


def test_correction_relevance_is_bounded_by_product_and_property():
    review = {'id': 'review', 'query': 'Masa PART123?', 'note': 'Recheck', 'rejected_evidence': []}
    assert applicable('Ce greutate are PART123?', [review]) == [review]
    assert applicable('masa OTHER999?', [review]) == []
    assert applicable('lungime PART123?', [review]) == []
    assert applicable('Cine produce acetona?', [review]) == []


def test_same_rejected_text_is_not_restored_by_another_upload_id():
    unit = {'id': 'new', 'doc_id': 'SRC-new', 'quote': 'PART123 masa 12 kg', 'fields': {}}
    review = {'rejected_evidence': [{**unit, 'id': 'old', 'doc_id': 'SRC-old'}]}
    assert excluded(unit, [review])
    assert not excluded({**unit, 'quote': 'PART123 masa 14 kg'}, [review])

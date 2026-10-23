import sys
from types import SimpleNamespace

import pytest

from app.rag.model_cache import cached_bge_model


INFERENCE_FILES = ('config.json', 'model.safetensors', 'tokenizer.json',
                   'colbert_linear.pt', 'sparse_linear.pt')


def write_model(folder):
    folder.mkdir(parents=True, exist_ok=True)
    for name in INFERENCE_FILES:
        (folder / name).write_bytes(b'fixture')
    return folder


@pytest.mark.parametrize('missing', INFERENCE_FILES)
def test_missing_inference_files_are_rejected(tmp_path, missing):
    folder = write_model(tmp_path / 'model')
    (folder / missing).unlink()
    with pytest.raises(FileNotFoundError, match='Offline BGE-M3'):
        cached_bge_model(str(folder))


def test_empty_or_broken_sparse_head_cannot_produce_random_retrieval_weights(tmp_path):
    folder = write_model(tmp_path / 'model')
    (folder / 'sparse_linear.pt').write_bytes(b'')
    with pytest.raises(FileNotFoundError):
        cached_bge_model(str(folder))
    (folder / 'sparse_linear.pt').unlink()
    (folder / 'sparse_linear.pt').symlink_to(folder / 'missing-blob')
    with pytest.raises(FileNotFoundError):
        cached_bge_model(str(folder))


def test_pytorch_and_sentencepiece_cache_is_supported(tmp_path):
    folder = write_model(tmp_path / 'model')
    (folder / 'model.safetensors').rename(folder / 'pytorch_model.bin')
    (folder / 'tokenizer.json').rename(folder / 'sentencepiece.bpe.model')
    assert cached_bge_model(str(folder)) == folder


def test_recent_hub_partial_snapshot_loads_offline_without_omitted_onnx(tmp_path, monkeypatch):
    hub = pytest.importorskip('huggingface_hub')
    tree_cache = pytest.importorskip('huggingface_hub._tree_cache')
    from huggingface_hub.errors import IncompleteSnapshotError
    import httpx

    cache = tmp_path / 'hub'
    storage = cache / 'models--BAAI--bge-m3'
    commit = 'a' * 40
    folder = write_model(storage / 'snapshots' / commit)
    (storage / 'refs').mkdir()
    (storage / 'refs' / 'main').write_text(commit)
    tree_cache.write_tree_cache(str(storage), commit, {
        name: tree_cache.TreeCacheEntry(size=7, blob_id='b' * 40)
        for name in (*INFERENCE_FILES, 'onnx/model.onnx', 'onnx/model.onnx_data')
    })
    monkeypatch.setattr(hub.constants, 'HF_HUB_CACHE', str(cache))
    monkeypatch.setattr(httpx.Client, 'send', lambda *a, **k: pytest.fail('Must remain offline'))
    # Reproduce the client's failure with a real recent Hub library.
    with pytest.raises(IncompleteSnapshotError):
        hub.snapshot_download('BAAI/bge-m3', local_files_only=True)
    assert cached_bge_model('BAAI/bge-m3') == folder

    loaded = []
    monkeypatch.setitem(sys.modules, 'FlagEmbedding', SimpleNamespace(
        BGEM3FlagModel=lambda model, **kwargs: loaded.append((model, kwargs))))
    from app.rag.index import BgeM3
    BgeM3('BAAI/bge-m3')
    # The public model loader receives the validated path, avoiding its own
    # whole-repo snapshot request as well as the diagnostic's previous failure.
    assert loaded == [(str(folder), {'use_fp16': False, 'devices': 'cpu'})]

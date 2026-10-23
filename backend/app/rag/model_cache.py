"""Resolve BGE-M3's inference files without requesting optional repo artifacts."""
from pathlib import Path


def cached_bge_model(model):
    folder = Path(model)
    if not folder.is_dir():
        from huggingface_hub import hf_hub_download
        # snapshot_download(local_files_only=True) also requires omitted ONNX
        # exports with recent Hub clients. Resolve one cached file instead.
        folder = Path(hf_hub_download(model, 'config.json', local_files_only=True)).parent

    def present(name):
        path = folder / name
        return path.is_file() and path.stat().st_size > 0

    required = ('config.json', 'colbert_linear.pt', 'sparse_linear.pt')
    if (not all(present(name) for name in required)
            or not any(present(name) for name in ('model.safetensors', 'pytorch_model.bin'))
            or not any(present(name) for name in ('tokenizer.json', 'sentencepiece.bpe.model'))):
        # Both heads are required: FlagEmbedding otherwise silently initializes
        # new random heads, invalidating the hybrid retrieval scores.
        raise FileNotFoundError('Offline BGE-M3 cache is missing inference files')
    return folder

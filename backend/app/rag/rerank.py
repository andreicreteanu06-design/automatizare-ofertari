"""Optional local FlagEmbedding reranker. Never downloads during requests."""
import logging
import math
import os
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)
_lock = Lock()
_model = None


def enabled():
    return os.environ.get('RERANK_ENABLED', 'false').lower() == 'true'


def compute_scores(pairs):
    global _model
    # Avoid concurrent CPU model loads/inference and duplicate RAM allocations.
    with _lock:
        if _model is None:
            model_path = Path(os.environ.get('RERANK_MODEL_PATH', '/models/reranker'))
            if not model_path.is_absolute() or not (model_path / 'config.json').is_file():
                raise FileNotFoundError('Prepare the reranker model with the setup profile')
            from FlagEmbedding import FlagReranker
            _model = FlagReranker(str(model_path), use_fp16=False, devices='cpu',
                                  batch_size=1, max_length=512, trust_remote_code=False)
        return _model.compute_score(pairs, batch_size=1, max_length=512, normalize=True)


def rerank(query, candidates, k, scorer=compute_scores):
    if not candidates:
        return [], 'empty'
    try:
        # Scoring truncation affects order only. Original excerpts remain untouched.
        scores = scorer([[query, c['text'][:6000]] for c in candidates])
        if isinstance(scores, (float, int)):
            scores = [scores]
        scores = [float(s) for s in scores]
        if len(scores) != len(candidates) or not all(math.isfinite(s) for s in scores):
            raise ValueError('Invalid reranker scores')
        ranked = sorted(zip(candidates, scores), key=lambda pair: pair[1], reverse=True)
        return [dict(c, rerank_score=s) for c, s in ranked[:k]], 'applied'
    except Exception as exc:
        # No prompts/documents or exception messages in logs.
        logger.warning('Local reranker unavailable (%s); retaining RRF order', type(exc).__name__)
        return candidates[:k], 'fallback'

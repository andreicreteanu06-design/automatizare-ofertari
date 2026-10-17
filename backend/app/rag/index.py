"""Qdrant + BGE-M3 hibrid: vector dens (semantic) + vector sparse (lexical, prinde
coduri și termeni tehnici exacți), combinate prin Reciprocal Rank Fusion."""
import os
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient, models

COLLECTION = "docs"
DENSE, SPARSE = "dense", "sparse"


class BgeM3:
    """BAAI/bge-m3 pe CPU (fp32, ~2.3 GB RAM). Offline: modelul vine din cache-ul HF montat."""
    dim = 1024

    def __init__(self, model=os.environ.get("BGE_M3_MODEL", "BAAI/bge-m3")):
        from FlagEmbedding import BGEM3FlagModel
        self._model = BGEM3FlagModel(model, use_fp16=False, devices="cpu")

    def embed(self, texts):
        """[(dense: list[float], sparse: {token_id: pondere})] pentru fiecare text."""
        out = self._model.encode(list(texts), batch_size=4, max_length=8192,
                                 return_dense=True, return_sparse=True)
        return [(d.tolist(), {int(k): float(v) for k, v in lw.items()})
                for d, lw in zip(out["dense_vecs"], out["lexical_weights"])]


def qdrant_client():
    return QdrantClient(url=os.environ["QDRANT_URL"], api_key=os.environ.get("QDRANT_API_KEY"),
                        https=False)  # rețea internă Docker; fără TLS, fără ieșire


def _sparse(weights):
    return models.SparseVector(indices=list(weights), values=list(weights.values()))


def ensure_collection(client, dim):
    if client.collection_exists(COLLECTION):
        return
    client.create_collection(
        COLLECTION,
        vectors_config={DENSE: models.VectorParams(size=dim, distance=models.Distance.COSINE)},
        sparse_vectors_config={SPARSE: models.SparseVectorParams()})
    client.create_payload_index(COLLECTION, "doc_id", models.PayloadSchemaType.KEYWORD)


def _doc_filter(doc_id):
    return models.Filter(must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))])


def index_chunks(client, embedder, chunks, meta):
    """(Re)indexează un document: șterge versiunea veche, apoi upsert. Idempotent."""
    ensure_collection(client, embedder.dim)
    client.delete(COLLECTION, points_selector=models.FilterSelector(filter=_doc_filter(meta.doc_id)))
    if not chunks:
        return
    vectors = embedder.embed(c.text for c in chunks)
    client.upsert(COLLECTION, [
        models.PointStruct(
            id=str(uuid5(NAMESPACE_URL, f"{c.doc_id}#{c.index}")),
            vector={DENSE: dense, SPARSE: _sparse(sparse)},
            payload={"doc_id": c.doc_id, "page": c.page_start, "page_end": c.page_end, "kind": c.kind,
                     "section": c.section, "text": c.text, "supplier": meta.supplier, 'provenance': list(c.provenance),
                     "manufacturer": meta.manufacturer, "doc_type": meta.doc_type, "source_revision": meta.source_revision})
        for c, (dense, sparse) in zip(chunks, vectors)])


def vector_search(client, embedder, query, k=5):
    """Top-k chunk-uri prin RRF peste căutarea densă și cea sparse.
    Fiecare rezultat are "cite": "[doc_id:pagina]" — formatul cerut în răspunsuri."""
    if not client.collection_exists(COLLECTION):
        return []
    ((dense, sparse),) = embedder.embed([query])
    prefetch = [models.Prefetch(query=dense, using=DENSE, limit=k * 4)]
    if sparse:  # o interogare fără tokeni lexicali utili ar da eroare pe vectorul sparse gol
        prefetch.append(models.Prefetch(query=_sparse(sparse), using=SPARSE, limit=k * 4))
    res = client.query_points(COLLECTION, prefetch=prefetch, query=models.FusionQuery(fusion=models.Fusion.RRF),
                              limit=k, with_payload=True)
    from app.sources import current_document
    freshness = {}
    for point in res.points:
        payload = point.payload
        key = (payload["doc_id"], payload.get("source_revision"))
        if key not in freshness:
            freshness[key] = current_document(*key)
    return [{**p.payload, "score": p.score, "cite": f"[{p.payload['doc_id']}:{p.payload['page']}]"}
            for p in res.points if freshness[(p.payload["doc_id"], p.payload.get("source_revision"))]]

from __future__ import annotations

import json
import math
import os
import re
import uuid
import zlib
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from pydantic import BaseModel
from mcp.server.fastmcp import FastMCP

from openai import OpenAI


from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    SparseVector,
    SparseVectorParams,
    PointStruct,
    VectorParams,
    Distance,
    NamedVector,
)

from dotenv import load_dotenv

load_dotenv()


mcp = FastMCP("Tools to add and search saved information from slack")

TOKEN_PATTERN = re.compile(r"[\w']+")
BM25_K1 = 1.5
BM25_B = 0.75
DEFAULT_EMBED_MODEL = "text-embedding-3-small"
EMBEDDING_SIZES = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
}


def _tokenize(text: str) -> List[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text)]


def _token_hash(token: str) -> int:
    return zlib.crc32(token.encode("utf-8")) & 0xFFFFFFFF


@dataclass
class MemoryRecord:
    id: str
    fact: str
    keywords: List[str]
    dense_vector: List[float]
    tokens: List[str]
    source_text: Optional[str]
    created_at: str

    @property
    def primary_keyword(self) -> Optional[str]:
        return self.keywords[0] if self.keywords else None

    def payload(self) -> Dict[str, Any]:
        return {
            "fact": self.fact,
            "keywords": self.keywords,
            "primary_keyword": self.primary_keyword,
            "source_text": self.source_text,
            "created_at": self.created_at,
            "tokens": self.tokens,
            "dense_vector": self.dense_vector,
        }

    def to_point(
        self,
        dense_name: str,
        sparse_name: str,
        sparse_vector: Optional[SparseVector],
    ) -> PointStruct:
        vectors: Dict[str, Any] = {dense_name: self.dense_vector}
        if sparse_vector is not None:
            vectors[sparse_name] = sparse_vector
        return PointStruct(id=self.id, vector=vectors, payload=self.payload())


class FactCandidateSchema(BaseModel):
    relevant_ids: list[str]


class FactSchema(BaseModel):
    fact: str
    keywords: list[str]


class MemoryExtractionSchema(BaseModel):
    memories: list[FactSchema]


class MemoryService:
    def __init__(self) -> None:
        self.collection_name = os.getenv("MEMORY_COLLECTION", "memories")
        self.dense_name = os.getenv("MEMORY_DENSE_VECTOR_NAME", "dense")
        self.sparse_name = os.getenv("MEMORY_SPARSE_VECTOR_NAME", "bm25")

        embed_model = os.getenv("MEMORY_EMBEDDING_MODEL", DEFAULT_EMBED_MODEL)
        self.embedding_model = embed_model
        self.embedding_dim = EMBEDDING_SIZES.get(
            embed_model, EMBEDDING_SIZES[DEFAULT_EMBED_MODEL]
        )

        llm_model = os.getenv("MEMORY_LLM_MODEL", "gpt-4.1-mini")
        self.llm_model = llm_model

        api_key = os.getenv("OPENAI_API_KEY")
        self.openai = OpenAI(api_key=api_key)

        qdrant_host = os.getenv("QDRANT_HOST", "localhost")
        qdrant_port = int(os.getenv("QDRANT_HTTP_PORT", "6333"))
        self.client = QdrantClient(host=qdrant_host, port=qdrant_port)

        self._ensure_collection()

    def _ensure_collection(self) -> None:
        if self.client.collection_exists(self.collection_name):
            return

        vector_params = {
            self.dense_name: VectorParams(
                size=self.embedding_dim,
                distance=Distance.COSINE,
            )
        }
        sparse_params = {
            self.sparse_name: SparseVectorParams(),
        }
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=vector_params,
            sparse_vectors_config=sparse_params,
        )

    # -----------------------
    # OpenAI helpers
    # -----------------------
    def _extract_memories(
        self, text: str, existing_keywords: List[str]
    ) -> List[Dict[str, Any]]:
        if not text or not text.strip():
            return []

        keyword_text = (
            ", ".join(existing_keywords[:50]) if existing_keywords else "None"
        )
        system_message = (
            "You extract atomic, self-contained factual memories from user notes. "
            "Return short statements that can stand on their own and relevant keyword tags."
        )
        user_message = (
            "Existing keywords: {keywords}.\n"
            "Break the following text into distinct facts."
            " Each fact must have at least one keyword."
            " Prefer existing keywords when suitable, otherwise propose concise new keywords.\n\n"
            "Text:\n{text}\n"
        ).format(keywords=keyword_text, text=text)

        response = self.openai.responses.parse(
            model=self.llm_model,
            input=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
            text_format=MemoryExtractionSchema,
        )

        try:
            data = json.loads(response.output_text)
        except json.JSONDecodeError as exc:  # pragma: no cover
            raise RuntimeError("Failed to parse memory extraction response") from exc

        memories = []
        for item in data.get("memories", []):
            fact = (item.get("fact") or "").strip()
            keywords = [
                kw.strip().lower() for kw in item.get("keywords", []) if kw.strip()
            ]
            if not fact:
                continue
            if not keywords:
                continue
            deduped = sorted(dict.fromkeys(keywords))
            memories.append({"fact": fact, "keywords": deduped})
        return memories

    def _filter_candidates(
        self, query: str, candidates: List[Dict[str, Any]]
    ) -> List[str]:
        if not candidates:
            return []

        payload = {
            "query": query,
            "candidates": [
                {
                    "id": candidate["id"],
                    "fact": candidate["fact"],
                    "keywords": candidate.get("keywords", []),
                }
                for candidate in candidates
            ],
        }

        system_message = "You filter search results to only those directly relevant to the user's query."
        user_message = (
            "Given the query and candidate memories below, return the ids that should be kept."
            "\n\n{payload}"
        ).format(payload=json.dumps(payload, ensure_ascii=False))

        response = self.openai.responses.parse(
            model=self.llm_model,
            input=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
            text_format=FactCandidateSchema,
        )

        try:
            data = json.loads(response.output_text)
        except json.JSONDecodeError as exc:  # pragma: no cover
            raise RuntimeError("Failed to parse memory filtering response") from exc

        return [item for item in data.get("relevant_ids", []) if item]

    def _embed(self, text: str) -> List[float]:
        response = self.openai.embeddings.create(
            model=self.embedding_model,
            input=text,
        )
        return list(response.data[0].embedding)

    # -----------------------
    # Qdrant helpers
    # -----------------------
    def _fetch_existing(self) -> List[MemoryRecord]:
        records: List[MemoryRecord] = []
        next_offset: Optional[int] = None

        while True:
            points, next_offset = self.client.scroll(
                collection_name=self.collection_name,
                offset=next_offset,
                limit=128,
                with_payload=True,
                with_vectors=True,
            )

            for point in points:
                payload = point.payload or {}
                fact = payload.get("fact")
                if not fact:
                    continue

                keywords = [str(kw) for kw in payload.get("keywords", [])]
                dense_vector: Optional[List[float]] = None

                if "dense_vector" in payload:
                    dense_vector = [float(val) for val in payload["dense_vector"]]

                vector_data = getattr(point, "vector", None)
                named_vectors = getattr(point, "vectors", None)

                if dense_vector is None and isinstance(vector_data, dict):
                    dense_candidate = vector_data.get(self.dense_name)
                    if dense_candidate is not None:
                        dense_vector = list(dense_candidate)

                if dense_vector is None and isinstance(named_vectors, dict):
                    dense_candidate = named_vectors.get(self.dense_name)
                    if dense_candidate is not None:
                        dense_vector = list(dense_candidate)

                if dense_vector is None:
                    continue

                tokens = payload.get("tokens")
                if not tokens:
                    tokens = _tokenize(fact)

                created_at = (
                    payload.get("created_at") or datetime.now(timezone.utc).isoformat()
                )
                source_text = payload.get("source_text")

                record = MemoryRecord(
                    id=str(point.id),
                    fact=fact,
                    keywords=keywords,
                    dense_vector=list(dense_vector),
                    tokens=list(tokens),
                    source_text=source_text,
                    created_at=created_at,
                )
                records.append(record)

            if next_offset is None:
                break

        return records

    # -----------------------
    # BM25 helpers
    # -----------------------
    def _collect_stats(
        self, records: Iterable[MemoryRecord]
    ) -> tuple[Counter, float, int]:
        doc_freq: Counter = Counter()
        total_len = 0
        valid_records = 0

        for record in records:
            if not record.tokens:
                continue
            valid_records += 1
            token_set = set(record.tokens)
            doc_freq.update(token_set)
            total_len += len(record.tokens)

        avgdl = (total_len / valid_records) if valid_records else 0.0
        return doc_freq, avgdl, valid_records

    def _build_sparse_vector(
        self,
        tokens: List[str],
        doc_freq: Counter,
        avgdl: float,
        total_docs: int,
    ) -> SparseVector:
        if not tokens or total_docs == 0:
            return SparseVector(indices=[], values=[])

        tf = Counter(tokens)
        doc_len = len(tokens)
        indices: List[int] = []
        values: List[float] = []

        for token, freq in tf.items():
            df = doc_freq.get(token, 0)
            if df == 0:
                continue
            idf = math.log((total_docs - df + 0.5) / (df + 0.5) + 1.0)
            denom = freq + BM25_K1 * (
                1 - BM25_B + BM25_B * (doc_len / avgdl if avgdl else 0)
            )
            if denom == 0:
                continue
            weight = idf * ((freq * (BM25_K1 + 1)) / denom)
            if weight <= 0:
                continue
            indices.append(_token_hash(token))
            values.append(weight)

        return SparseVector(indices=indices, values=values)

    def _bm25_score(
        self,
        query_counts: Counter,
        record: MemoryRecord,
        doc_freq: Counter,
        avgdl: float,
        total_docs: int,
    ) -> float:
        if not record.tokens or total_docs == 0:
            return 0.0

        tf = Counter(record.tokens)
        doc_len = len(record.tokens)
        score = 0.0

        for token, freq_q in query_counts.items():
            df = doc_freq.get(token, 0)
            if df == 0:
                continue
            idf = math.log((total_docs - df + 0.5) / (df + 0.5) + 1.0)
            freq_d = tf.get(token, 0)
            if freq_d == 0:
                continue
            denom = freq_d + BM25_K1 * (
                1 - BM25_B + BM25_B * (doc_len / avgdl if avgdl else 0)
            )
            if denom == 0:
                continue
            score += idf * ((freq_d * (BM25_K1 + 1)) / denom)

        return score

    # -----------------------
    # Public API
    # -----------------------
    def save(self, text: str) -> Dict[str, Any]:
        existing_records = self._fetch_existing()
        existing_keywords = sorted(
            {kw for record in existing_records for kw in record.keywords}
        )

        extracted = self._extract_memories(text, existing_keywords)
        if not extracted:
            return {"saved": 0, "message": "No factual memories detected."}

        new_records: List[MemoryRecord] = []
        now_iso = datetime.now(timezone.utc).isoformat()
        for item in extracted:
            fact = item["fact"]
            keywords = item["keywords"]
            embedding = self._embed(fact)
            tokens = _tokenize(fact)
            record = MemoryRecord(
                id=str(uuid.uuid4()),
                fact=fact,
                keywords=keywords,
                dense_vector=embedding,
                tokens=tokens,
                source_text=text,
                created_at=now_iso,
            )
            new_records.append(record)

        all_records = existing_records + new_records
        doc_freq, avgdl, total_docs = self._collect_stats(all_records)

        points = []
        for record in all_records:
            sparse_vector = self._build_sparse_vector(
                record.tokens,
                doc_freq,
                avgdl,
                total_docs,
            )
            points.append(
                record.to_point(self.dense_name, self.sparse_name, sparse_vector)
            )

        self.client.upsert(collection_name=self.collection_name, points=points)

        return {
            "saved": len(new_records),
            "facts": [record.fact for record in new_records],
            "keywords": sorted(
                {kw for record in new_records for kw in record.keywords}
            ),
        }

    def search(
        self,
        query: str,
        limit: int = 6,
        group_size: int = 3,
    ) -> List[Dict[str, Any]]:
        records = self._fetch_existing()
        if not records:
            return []

        dense_query = self._embed(query)
        query_tokens = _tokenize(query)
        query_counts = Counter(query_tokens)

        doc_freq, avgdl, total_docs = self._collect_stats(records)
        if not query_counts:
            return []

        search_groups_result = self.client.search_groups(
            collection_name=self.collection_name,
            query_vector=NamedVector(name=self.dense_name, vector=dense_query),
            limit=max(1, limit),
            group_by="primary_keyword",
            group_size=max(1, group_size),
            with_payload=True,
        )

        groups = getattr(search_groups_result, "groups", None)
        if groups is None:
            if isinstance(search_groups_result, tuple):
                groups = search_groups_result[0]
            else:
                groups = search_groups_result

        if not groups:
            return []

        record_by_id = {record.id: record for record in records}
        candidates: List[Dict[str, Any]] = []

        for group in groups:
            hits = getattr(group, "hits", None)
            if hits is None:
                if isinstance(group, tuple) and len(group) >= 2:
                    hits = group[1]
                elif isinstance(group, dict):
                    hits = group.get("hits")
            if not hits:
                continue

            for point in hits:
                record = record_by_id.get(str(point.id))
                if not record:
                    payload = point.payload or {}
                    fact = payload.get("fact")
                    if not fact:
                        continue
                    tokens = payload.get("tokens") or _tokenize(fact)
                    dense_vector = payload.get("dense_vector")
                    if dense_vector is None:
                        continue
                    record = MemoryRecord(
                        id=str(point.id),
                        fact=fact,
                        keywords=[str(kw) for kw in payload.get("keywords", [])],
                        dense_vector=list(dense_vector),
                        tokens=list(tokens),
                        source_text=payload.get("source_text"),
                        created_at=payload.get("created_at")
                        or datetime.now(timezone.utc).isoformat(),
                    )
                bm25_score = self._bm25_score(
                    query_counts, record, doc_freq, avgdl, total_docs
                )
                candidates.append(
                    {
                        "id": record.id,
                        "fact": record.fact,
                        "keywords": record.keywords,
                        "created_at": record.created_at,
                        "source_text": record.source_text,
                        "dense_score": float(getattr(point, "score", 0.0)),
                        "bm25_score": bm25_score,
                    }
                )

        if not candidates:
            return []

        dense_values = [candidate["dense_score"] for candidate in candidates]
        bm25_values = [candidate["bm25_score"] for candidate in candidates]

        def _normalize(values: List[float], value: float) -> float:
            if not values:
                return 0.0
            min_v = min(values)
            max_v = max(values)
            if max_v == min_v:
                return 0.5
            return (value - min_v) / (max_v - min_v)

        for candidate in candidates:
            dense_norm = _normalize(dense_values, candidate["dense_score"])
            bm25_norm = _normalize(bm25_values, candidate["bm25_score"])
            candidate["score"] = 0.6 * dense_norm + 0.4 * bm25_norm

        candidates.sort(key=lambda item: item["score"], reverse=True)
        top_candidates = candidates[:limit]

        relevant_ids = set(self._filter_candidates(query, top_candidates))
        filtered = [
            candidate for candidate in top_candidates if candidate["id"] in relevant_ids
        ]

        return [
            {
                "id": candidate["id"],
                "fact": candidate["fact"],
                "keywords": candidate["keywords"],
                "created_at": candidate["created_at"],
                "score": candidate["score"],
            }
            for candidate in filtered
        ]


_service: Optional[MemoryService] = None


def get_service() -> MemoryService:
    global _service
    if _service is None:
        _service = MemoryService()
    return _service


@mcp.tool()
def save_memory(text: str) -> Dict[str, Any]:
    """
    Save something to a memory group.

    This tool parses out facts from a text blob and saves them into a memory base.

    This will return all the text blobs that were saved and where they were saved to.
    """
    service = get_service()
    return service.save(text)


@mcp.tool()
def search_memory(
    query: str, limit: int = 6, group_size: int = 3
) -> List[Dict[str, Any]]:
    """
    Tool to search memories for infomation stored previously.
    Anything can be stored in memories.
    It may not know anything about your request.
    """
    service = get_service()
    return service.search(query, limit=limit, group_size=group_size)


if __name__ == "__main__":
    mcp.run(transport="stdio")

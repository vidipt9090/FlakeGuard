"""Embed code chunks into Chroma and search them (work package B5).

    python -m flakeguard.retrieval.embed --repo ../cachetools \
        --query "cache eviction" -k 3

This is the seed of the Eval 2 retriever, not the finished thing. It exists to
answer one question now: does semantic search over code chunks return anything
a person would call relevant, on a laptop with 4 GB of VRAM?

chromadb and sentence-transformers are imported lazily, inside the functions
that need them. They pull in PyTorch, roughly 2.5 GB, and nothing else in
flakeguard needs them. CI installs `.[dev]` and never pays that cost; the
chunking underneath is pure `ast` and is tested without them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from flakeguard.contracts import Chunk
from flakeguard.retrieval.chunker import chunk_repo

# Verified by installing on laptop 1, Python 3.12: this is the exact name on
# Hugging Face. 384 dimensions, ~130 MB, runs on CPU in a couple of minutes
# for a repo this size, so the 3050's 4 GB is not a constraint here.
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"

# bge models are trained to embed queries with an instruction prefix and
# documents without one. Skipping this costs real accuracy, and it is the
# single easiest thing to get wrong with this family of models.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def embedding_text(chunk: Chunk) -> str:
    """What actually gets embedded for a chunk.

    The raw source alone performs badly: every function in cachetools mentions
    "cache", so a query like "cache eviction" matches almost uniformly and the
    ranking is close to arbitrary. Prefixing the module path and the kind
    gives the model the one piece of context the source text does not carry --
    where this code lives and what it is. Measured difference is in
    docs/eval1/retrieval-notes.md.
    """
    module = chunk.path.replace("/", ".").removesuffix(".py")
    return f"{chunk.kind} in {module}\n\n{chunk.text}"


def collection_name(repo: str) -> str:
    """A Chroma-legal collection name for a repo label.

    Chroma requires 3-512 characters from [a-zA-Z0-9._-], starting and ending
    alphanumeric. Repo labels do not have to obey that: "ct" is too short and
    an owner/name label contains a slash, and either crashes the client.
    """
    cleaned = "".join(c if (c.isalnum() or c in "._-") else "-" for c in repo)
    cleaned = cleaned.strip("._-") or "repo"
    if len(cleaned) < 3:
        cleaned = f"{cleaned}-idx"
    return cleaned[:512]


def _collection(persist_dir: Path, name: str, reset: bool):
    import chromadb

    safe = collection_name(name)
    client = chromadb.PersistentClient(path=str(persist_dir))
    if reset:
        try:
            client.delete_collection(safe)
        except Exception:
            pass  # first run, nothing to delete
    # Cosine distance, because embeddings are compared by direction, not
    # magnitude; Chroma's default is squared L2.
    return client.get_or_create_collection(safe, metadata={"hnsw:space": "cosine"})


def build_index(
    repo_root: str | Path,
    persist_dir: str | Path,
    repo: str = "repo",
    sha: str = "local",
    model_name: str = DEFAULT_MODEL,
    reset: bool = True,
    with_context: bool = True,
) -> int:
    """Chunk the repo, embed every chunk, store it. Returns the chunk count."""
    from sentence_transformers import SentenceTransformer

    chunks = chunk_repo(repo_root, repo=repo, sha=sha)
    if not chunks:
        return 0

    model = SentenceTransformer(model_name)
    texts = [embedding_text(c) if with_context else c.text for c in chunks]
    embeddings = model.encode(texts, batch_size=32, show_progress_bar=False).tolist()

    collection = _collection(Path(persist_dir), repo, reset)
    # Chroma rejects oversized batches; this repo fits well inside one, but
    # Emma will not.
    step = 500
    for i in range(0, len(chunks), step):
        part = chunks[i : i + step]
        collection.add(
            ids=[c.chunk_id for c in part],
            documents=[c.text for c in part],
            embeddings=embeddings[i : i + step],
            metadatas=[
                {
                    "path": c.path,
                    "start_line": c.start_line,
                    "end_line": c.end_line,
                    "kind": c.kind,
                }
                for c in part
            ],
        )
    return len(chunks)


def search(
    query: str,
    persist_dir: str | Path,
    repo: str = "repo",
    k: int = 3,
    model_name: str = DEFAULT_MODEL,
) -> list[Chunk]:
    """Top-k chunks for a natural language query."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)
    vector = model.encode([QUERY_PREFIX + query]).tolist()

    collection = _collection(Path(persist_dir), repo, reset=False)
    result = collection.query(query_embeddings=vector, n_results=k)

    out: list[Chunk] = []
    ids = result["ids"][0]
    docs = result["documents"][0]
    metas = result["metadatas"][0]
    dists = result["distances"][0]
    for chunk_id, text, meta, dist in zip(ids, docs, metas, dists):
        out.append(
            Chunk(
                chunk_id=chunk_id,
                path=str(meta["path"]),
                start_line=int(meta["start_line"]),
                end_line=int(meta["end_line"]),
                kind=str(meta["kind"]),
                text=text,
                # Cosine distance to similarity, so bigger is better and the
                # field means the same thing as score elsewhere.
                score=round(1.0 - float(dist), 4),
            )
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m flakeguard.retrieval.embed")
    parser.add_argument("--repo", required=True, help="path to the checkout to index")
    parser.add_argument("--repo-name", default=None)
    parser.add_argument("--sha", default="local")
    parser.add_argument("--query", required=True)
    parser.add_argument("-k", type=int, default=3)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--persist", default="data/chroma", help="where the index is stored"
    )
    parser.add_argument(
        "--no-build", action="store_true", help="query an index built earlier"
    )
    parser.add_argument("--preview", type=int, default=3, metavar="N")
    parser.add_argument(
        "--raw",
        action="store_true",
        help="embed the source alone, without the path/kind header",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    if not repo_root.is_dir():
        print(f"error: --repo {repo_root} is not a directory", file=sys.stderr)
        return 2
    name = args.repo_name or repo_root.name

    if not args.no_build:
        count = build_index(
            repo_root,
            args.persist,
            repo=name,
            sha=args.sha,
            model_name=args.model,
            with_context=not args.raw,
        )
        print(f"indexed {count} chunks from {name} into {args.persist}\n")

    hits = search(args.query, args.persist, repo=name, k=args.k, model_name=args.model)
    print(f'query: "{args.query}"  (top {len(hits)})')
    print("=" * 72)
    for i, chunk in enumerate(hits, 1):
        print(
            f"{i}. {chunk.path}:{chunk.start_line}-{chunk.end_line}"
            f"  [{chunk.kind}]  similarity {chunk.score:.3f}"
        )
        for line in chunk.text.splitlines()[: args.preview]:
            print(f"     | {line}")
        print()
    return 0 if hits else 1


if __name__ == "__main__":
    raise SystemExit(main())

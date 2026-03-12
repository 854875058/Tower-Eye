import argparse
import json
from pathlib import Path
from typing import List, Tuple

from poc.pipeline.utils import connect_db, load_yaml, resolve_path

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    np = None

try:
    import faiss  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    faiss = None


def load_embeddings(conn) -> Tuple[List[str], List[Path]]:
    rows = conn.execute(
        "SELECT asset_id, vector_path FROM embeddings ORDER BY asset_id"
    ).fetchall()
    asset_ids = [row["asset_id"] for row in rows]
    paths = [Path(row["vector_path"]) for row in rows]
    return asset_ids, paths


def build_faiss_index(vectors: "np.ndarray"):
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description="POC vector index builder")
    parser.add_argument("--config", default="poc/config/poc.yaml")
    parser.add_argument("--output-dir", default="data/index")
    args = parser.parse_args()

    if np is None:
        raise RuntimeError("numpy is required. Please pip install numpy.")

    config = load_yaml(args.config)
    paths_cfg = config.get("paths", {})
    db_path = resolve_path(paths_cfg.get("db_path", "data/metadata.db"))
    output_dir = resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    conn = connect_db(db_path)
    asset_ids, vec_paths = load_embeddings(conn)
    conn.close()

    if not asset_ids:
        raise RuntimeError("no embeddings found, run poc.pipeline.embed first.")

    vectors = []
    for path in vec_paths:
        vectors.append(np.load(path))
    vectors = np.vstack(vectors).astype("float32")

    meta = {
        "asset_ids": asset_ids,
        "dims": int(vectors.shape[1]),
        "backend": "faiss" if faiss else "numpy",
    }

    if faiss:
        index = build_faiss_index(vectors)
        index_path = output_dir / "index.faiss"
        faiss.write_index(index, str(index_path))
    else:
        index_path = output_dir / "index.npy"
        np.save(index_path, vectors)

    meta_path = output_dir / "index_meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")

    print(f"index built: {index_path}")


if __name__ == "__main__":
    main()


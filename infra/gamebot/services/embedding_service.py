"""Embedding generation service. Run this on monster-gpu."""
import os
import sys
import hashlib
import json
from typing import List, Dict
import numpy as np
from sentence_transformers import SentenceTransformer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MODEL_NAME = "/tmp/model_test"
BATCH_SIZE = 64


def build_text(game: Dict) -> str:
    parts = [f"Title: {game.get('title', '')}"]
    if game.get("genres"):
        parts.append(f"Genres: {game['genres']}")
    if game.get("tags"):
        parts.append(f"Tags: {game['tags']}")
    if game.get("description"):
        desc = game["description"][:500]
        parts.append(f"Description: {desc}")
    return ". ".join(parts)


def compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:64]


def generate_embeddings(games: List[Dict]) -> List[Dict]:
    model = SentenceTransformer(MODEL_NAME, device="cuda")
    texts = [build_text(g) for g in games]
    hashes = [compute_hash(t) for t in texts]
    embeddings = model.encode(texts, batch_size=BATCH_SIZE, show_progress_bar=True, convert_to_numpy=True)

    results = []
    for game, emb, h in zip(games, embeddings, hashes):
        results.append({
            "game_id": game["id"],
            "embedding": emb.tolist(),
            "text_hash": h,
            "model_version": MODEL_NAME,
        })
    return results


def main():
    games = json.load(sys.stdin)
    results = generate_embeddings(games)
    json.dump(results, sys.stdout)


if __name__ == "__main__":
    main()

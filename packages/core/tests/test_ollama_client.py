# packages/core/tests/test_ollama_client.py
"""
Real Ollama tests for stream, embed, batch_embed.
Requires Ollama to be running with gemma4:12b-it-qat and nomic-embed-text:v1.5.
"""
from __future__ import annotations

import pytest

from vein_core.ollama_client import OllamaClient, Message


@pytest.fixture
def client():
    """OllamaClient with real config - no mocking."""
    from vein_core.config import get_config
    cfg = get_config()
    yield OllamaClient(cfg=cfg)


class TestOllamaClient:
    """Real Ollama tests for stream, embed, batch_embed."""

    @pytest.mark.asyncio
    async def test_stream(self, client):
        """Stream from real Ollama - see actual output."""
        print("\n=== test_stream ===")
        
        async for chunk in client.stream([Message(role="user", content="Say 'hello' in one word")]):
            print(chunk, end="", flush=True)
        
        print("\n")

    @pytest.mark.asyncio
    async def test_embed(self, client):
        """Get real embedding from Ollama."""
        print("\n=== test_embed ===")
        
        vector = await client.embed("Hello world")
        
        print(f"vector length: {len(vector)}")
        print(f"first 10 values: {vector[:10]}")
        
        return vector

    @pytest.mark.asyncio
    async def test_batch_embed(self, client):
        """Get real batch embeddings from Ollama."""
        print("\n=== test_batch_embed ===")
        
        vectors = await client.batch_embed(["Hello world", "Python is great", "Machine learning"])
        
        for i, v in enumerate(vectors):
            print(f"[{i}] length: {len(v)}, first 5: {v[:5]}")
        
        return vectors
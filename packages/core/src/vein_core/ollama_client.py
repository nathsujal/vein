from __future__ import annotations

import time
import asyncio
import json as _json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, AsyncIterator

import httpx

from .domain import ServiceStatus
from .ports import Probeable, ModelVerifiable

if TYPE_CHECKING:
    from vein_core.config import AppConfig


class OllamaClient(Probeable, ModelVerifiable):

    SERVICE_NAME = "ollama"

    def __init__(self, cfg: AppConfig) -> None:
        self._llm_cfg = cfg.llm
        self._embedder_cfg = cfg.embedder
        
        self._url = self._llm_cfg.provider.base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._url,
            timeout=self._llm_cfg.provider.timeout_seconds,
        )
        self._available_models: list[str] | None = None

    @property
    def available_models(self) -> list[str]:
        return self._available_models or []

    async def probe(self) -> ServiceStatus:
        t0 = time.perf_counter()

        try:
            resp = await self._client.get("/api/tags")
            elapsed_ms = (time.perf_counter() - t0) * 1000
            resp.raise_for_status()

            body = resp.json()
            all_models = [m["name"] for m in body.get("models", [])]
            self._available_models = [m for m in all_models if ":cloud" not in m]

            detail = (
                f"{len(self._available_models)} model(s): {', '.join(self._available_models)}"
                if self._available_models
                else "no models pulled yet - run: ollama pull <model>"
            )
            healthy = True

        except httpx.ConnectError as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            detail = f"connection refused: {exc}"
            healthy = False

        except httpx.TimeoutException:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            detail = f"timed out after {self._llm_cfg.provider.timeout_seconds}s"
            healthy = False

        except httpx.HTTPStatusError as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            detail = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            healthy = False

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            detail = f"unexpected error: {exc}"
            healthy = False

        return ServiceStatus(
            name=self.SERVICE_NAME,
            healthy=healthy,
            latency_ms=round(elapsed_ms, 2),
            detail=detail,
        )

    async def verify_model(self, model: str) -> ServiceStatus:
        if self._available_models is None:
            return ServiceStatus(
                name=self.SERVICE_NAME,
                healthy=False,
                latency_ms=0,
                detail="model availability unknown - run probe first",
            )
        if model not in self._available_models:
            return ServiceStatus(
                name=self.SERVICE_NAME,
                healthy=False,
                latency_ms=0,
                detail=f"model {model!r} not available - pull it with: `ollama pull {model}`",
            )
        return ServiceStatus(
            name=self.SERVICE_NAME,
            healthy=True,
            latency_ms=0,
            detail=f"model {model!r} is available",
        )

    async def stream(
        self,
        messages: list[Message],
        *,
        model: str | None = None,
        temperature: float | None = None,
        top_k: int | None = None,
        top_p: float | None = None,
        num_predict: int | None = None,
        repeat_penalty: float | None = None,
    ) -> AsyncIterator[str]:
        model = model or self._llm_cfg.model
        max_retries = self._llm_cfg.provider.max_retries
        messages_dict = [m.to_dict() for m in messages]

        last_exception: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                async for part in self._stream_post(
                    "/api/chat",
                    json={
                        "model": model,
                        "messages": messages_dict,
                        "stream": True,
                        "think": True,
                        "keep_alive": "5m",
                        "options": {
                            "temperature": temperature,
                            "top_k": top_k,
                            "top_p": top_p,
                            "num_predict": num_predict,
                            "repeat_penalty": repeat_penalty,
                        },
                    },
                ):
                    if "message" in part and part["message"].get("content"):
                        yield part["message"]["content"]
                return

            except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
                last_exception = e
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)
                continue

        if last_exception:
            raise last_exception

    async def embed(
        self,
        text: str,
        *,
        model: str | None = None,
    ) -> list[float]:
        model = model or self._embedder_cfg.model
        max_retries = self._embedder_cfg.provider.max_retries

        last_exception: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                resp = await self._post(
                    "/api/embed",
                    json={
                        "model": model,
                        "input": text,
                    },
                )
                return resp["embeddings"][0]
            except Exception as e:
                last_exception = e
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)
                continue

        if last_exception:
            raise last_exception

    async def batch_embed(
        self,
        texts: list[str],
        *,
        as_query: bool = False,
        model: str | None = None,
    ) -> list[list[float]]:
        if not texts:
            raise ValueError("texts must not be empty")

        model = model or self._embedder_cfg.model
        max_retries = self._embedder_cfg.provider.max_retries

        last_exception: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                resp = await self._post(
                    "/api/embed",
                    json={
                        "model": model,
                        "input": texts,
                    },
                )
                return resp["embeddings"]
            except Exception as e:
                last_exception = e
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)
                continue

        if last_exception:
            raise last_exception

    async def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        await self._client.aclose()


    async def _post(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        resp = await self._client.post(path, json=json)
        resp.raise_for_status()
        return resp.json()

    async def _stream_post(
        self,
        path: str,
        json: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        async with self._client.stream("POST", path, json=json) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = line.strip()
                if line:
                    yield _json.loads(line)


@dataclass(slots=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(slots=True)
class Query:
    text: str
    intent: str | None = None
    rewritten_query: str | None = None
    temperature: float | None = None
    top_k: int | None = None
    top_p: float | None = None
    min_p: float = 0.0
    num_predict: int | None = None
    repeat_penalty: float | None = None
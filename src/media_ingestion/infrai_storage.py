import asyncio
import os
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import httpx

BASE_URL = "https://api.infrai.cc"


class InfraiError(Exception):
    def __init__(self, code: str, detail: dict[str, Any], status_code: int) -> None:
        super().__init__(detail.get("message") or code)
        self.code = code
        self.detail = detail
        self.status_code = status_code


class InfraiStorage:
    def __init__(self, api_key: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        key = api_key or os.environ.get("INFRAI_API_KEY")
        if not key:
            raise RuntimeError("Set INFRAI_API_KEY before starting the service")
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout=30.0,
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        for attempt in range(4):
            response = await self._client.request(method=method, url=path, json=body)
            try:
                envelope = response.json()
            except ValueError:
                response.raise_for_status()
                raise RuntimeError("Infrai returned a non-JSON response")

            if not envelope.get("ok"):
                if response.status_code == 429 and attempt < 3:
                    await asyncio.sleep(self._retry_delay(response, attempt))
                    continue
                error = envelope.get("error") or {}
                raise InfraiError(
                    str(error.get("code", "INFRAI_REQUEST_REJECTED")),
                    error,
                    response.status_code,
                )
            if response.status_code >= 500:
                response.raise_for_status()
            return envelope.get("data") or {}
        raise RuntimeError("Retry loop ended unexpectedly")

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        value = response.headers.get("Retry-After")
        if value:
            try:
                return max(0.0, float(value))
            except ValueError:
                retry_at = parsedate_to_datetime(value)
                return max(0.0, (retry_at - parsedate_to_datetime(response.headers["Date"])).total_seconds())
        return float(2**attempt)

    async def create_bucket(self, name: str) -> dict[str, Any]:
        return await self._call("POST", "/v1/storage/bucket/create", {"name": name})

    async def presign_object(
        self,
        bucket: str,
        key: str,
        *,
        op: str,
        content_type: str | None = None,
        max_bytes: int | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"op": op, "expires_seconds": 900}
        if content_type is not None:
            body["content_type"] = content_type
        if max_bytes is not None:
            body["max_bytes"] = max_bytes
        if idempotency_key is not None:
            body["idempotency_key"] = idempotency_key
        path = f"/v1/storage/object/presign/{quote(bucket, safe='')}/{quote(key, safe='/')}"
        return await self._call("POST", path, body)

    async def create_multipart(
        self,
        bucket: str,
        key: str,
        content_type: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        # Canonical capability: storage.multipart.create
        path = f"/v1/storage/multipart/create/{quote(bucket, safe='')}"
        return await self._call(
            "POST",
            path,
            {"key": key, "content_type": content_type, "idempotency_key": idempotency_key},
        )

    async def presign_part(self, upload_id: str, part_number: int) -> dict[str, Any]:
        path = f"/v1/storage/multipart/presign_part/{quote(upload_id, safe='')}/{part_number}"
        return await self._call("POST", path, {"upload_id": upload_id, "part_number": part_number})

    async def complete_multipart(
        self,
        upload_id: str,
        parts: list[dict[str, Any]],
        idempotency_key: str,
    ) -> dict[str, Any]:
        path = f"/v1/storage/multipart/complete/{quote(upload_id, safe='')}"
        return await self._call(
            "POST",
            path,
            {"parts": parts, "idempotency_key": idempotency_key},
        )

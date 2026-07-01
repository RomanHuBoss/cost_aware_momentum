from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx


class BybitAPIError(RuntimeError):
    def __init__(self, code: int | str, message: str, payload: dict | None = None):
        super().__init__(f"Bybit API error {code}: {message}")
        self.code = code
        self.message = message
        self.payload = payload or {}


@dataclass(frozen=True)
class BybitResponse:
    result: dict
    server_time_ms: int | None
    raw: dict


class BybitClient:
    """Bybit V5 client intentionally exposing only public and read-only GET operations."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        api_secret: str | None = None,
        recv_window: int = 5000,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self.recv_window = recv_window
        self.client = httpx.AsyncClient(
            base_url=self.base_url, timeout=timeout, headers={"User-Agent": "cost-aware-momentum/1.0"}
        )
        self._semaphore = asyncio.Semaphore(5)

    async def close(self) -> None:
        await self.client.aclose()

    async def _get(
        self, path: str, params: dict[str, Any] | None = None, private: bool = False
    ) -> BybitResponse:
        params = {key: value for key, value in (params or {}).items() if value is not None}
        if private and (not self.api_key or not self.api_secret):
            raise BybitAPIError("AUTH", "Read-only credentials are not configured")
        last_error: Exception | None = None
        async with self._semaphore:
            for attempt in range(4):
                try:
                    request_params: dict[str, Any] | list[tuple[str, str]] = params
                    if private:
                        request_params = sorted((str(k), str(v)) for k, v in params.items())
                    request = self.client.build_request("GET", path, params=request_params)
                    if private:
                        timestamp = str(int(time.time() * 1000))
                        query = request.url.query.decode("ascii")
                        plain = f"{timestamp}{self.api_key}{self.recv_window}{query}"
                        signature = hmac.new(
                            self.api_secret.encode(), plain.encode(), hashlib.sha256
                        ).hexdigest()
                        request.headers.update(
                            {
                                "X-BAPI-API-KEY": self.api_key,
                                "X-BAPI-SIGN": signature,
                                "X-BAPI-SIGN-TYPE": "2",
                                "X-BAPI-TIMESTAMP": timestamp,
                                "X-BAPI-RECV-WINDOW": str(self.recv_window),
                            }
                        )
                    response = await self.client.send(request)
                    response.raise_for_status()
                    payload = response.json()
                    if payload.get("retCode") != 0:
                        raise BybitAPIError(
                            payload.get("retCode"), payload.get("retMsg", "Unknown error"), payload
                        )
                    return BybitResponse(payload.get("result") or {}, payload.get("time"), payload)
                except (httpx.HTTPError, json.JSONDecodeError, BybitAPIError) as exc:
                    last_error = exc
                    if isinstance(exc, BybitAPIError) and exc.code not in {10006, 10002}:
                        raise
                    await asyncio.sleep(min(8.0, 0.5 * 2**attempt))
        raise RuntimeError("Bybit request failed") from last_error

    async def get_server_time(self) -> BybitResponse:
        return await self._get("/v5/market/time")

    async def get_instruments(self, category: str = "linear") -> list[dict]:
        items: list[dict] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            params: dict[str, Any] = {"category": category, "limit": 1000}
            if cursor is not None:
                params["cursor"] = cursor
            result = (await self._get("/v5/market/instruments-info", params)).result
            page = result.get("list") or []
            if not isinstance(page, list):
                raise RuntimeError("Bybit instruments response list is invalid")
            items.extend(page)

            next_cursor = str(result.get("nextPageCursor") or "").strip()
            if not next_cursor:
                return items
            if next_cursor in seen_cursors:
                raise RuntimeError("Bybit instruments pagination repeated a cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

    async def get_tickers(self, category: str = "linear", symbol: str | None = None) -> list[dict]:
        response = await self._get("/v5/market/tickers", {"category": category, "symbol": symbol})
        return response.result.get("list") or []

    async def get_kline(
        self,
        symbol: str,
        *,
        interval: str = "60",
        limit: int = 200,
        start_ms: int | None = None,
        end_ms: int | None = None,
        price_type: str = "last",
    ) -> list[list[str]]:
        endpoint = {
            "last": "/v5/market/kline",
            "mark": "/v5/market/mark-price-kline",
            "index": "/v5/market/index-price-kline",
        }[price_type]
        response = await self._get(
            endpoint,
            {
                "category": "linear",
                "symbol": symbol,
                "interval": interval,
                "limit": min(limit, 1000),
                "start": start_ms,
                "end": end_ms,
            },
        )
        return response.result.get("list") or []

    async def get_funding_history(self, symbol: str, limit: int = 50) -> list[dict]:
        response = await self._get(
            "/v5/market/funding/history",
            {"category": "linear", "symbol": symbol, "limit": min(limit, 200)},
        )
        return response.result.get("list") or []

    async def get_open_interest(self, symbol: str, interval: str = "1h", limit: int = 50) -> list[dict]:
        response = await self._get(
            "/v5/market/open-interest",
            {"category": "linear", "symbol": symbol, "intervalTime": interval, "limit": min(limit, 200)},
        )
        return response.result.get("list") or []

    async def get_orderbook(self, symbol: str, limit: int = 50) -> dict:
        response = await self._get(
            "/v5/market/orderbook", {"category": "linear", "symbol": symbol, "limit": limit}
        )
        return response.result

    async def get_wallet_balance(self, account_type: str = "UNIFIED") -> dict:
        return (
            await self._get("/v5/account/wallet-balance", {"accountType": account_type}, private=True)
        ).result

    async def get_positions(self, settle_coin: str = "USDT") -> list[dict]:
        positions: list[dict] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            params: dict[str, Any] = {
                "category": "linear",
                "settleCoin": settle_coin,
                "limit": 200,
            }
            if cursor is not None:
                params["cursor"] = cursor
            result = (await self._get("/v5/position/list", params, private=True)).result
            page = result.get("list") or []
            if not isinstance(page, list):
                raise RuntimeError("Bybit positions response list is invalid")
            positions.extend(page)

            next_cursor = str(result.get("nextPageCursor") or "").strip()
            if not next_cursor:
                return positions
            if next_cursor in seen_cursors:
                raise RuntimeError("Bybit positions pagination repeated a cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

    async def get_fee_rate(self, symbol: str | None = None) -> list[dict]:
        result = (
            await self._get("/v5/account/fee-rate", {"category": "linear", "symbol": symbol}, private=True)
        ).result
        return result.get("list") or []

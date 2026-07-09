from __future__ import annotations

import pytest

from app.bybit.client import BybitClient, BybitResponse


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        ("get_tickers", ("linear",)),
        ("get_kline", ("BTCUSDT",)),
        ("get_fee_rate", ("BTCUSDT",)),
    ],
)
async def test_bybit_list_endpoints_reject_non_list_payloads(monkeypatch, method_name: str, args: tuple[object, ...]) -> None:
    async def fake_get(self, path, params=None, private=False):
        return BybitResponse(result={"list": {"not": "a-list"}}, server_time_ms=0, raw={})

    monkeypatch.setattr(BybitClient, "_get", fake_get)
    client = BybitClient(base_url="https://example.invalid", api_key="read", api_secret="secret")
    try:
        with pytest.raises(RuntimeError, match="response list is invalid"):
            await getattr(client, method_name)(*args)
    finally:
        await client.close()

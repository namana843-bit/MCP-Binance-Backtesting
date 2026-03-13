"""Module-level Binance USD-M Futures client (ccxt async, singleton).

Public API
----------
await get_exchange()                           -> initialized ccxt.binanceusdm exchange
await fetch_ticker(symbol)                    -> dict with last/bid/ask/high/low/volume
await fetch_ohlcv(symbol, tf)                 -> list of OHLCV dicts
await fetch_order_book(symbol, limit)         -> dict with bids/asks lists
await fetch_futures_symbols()                 -> sorted list of active USDT-M perp symbols
await fetch_volume_ranked_symbols(top_n)      -> symbols sorted by 24h quote volume desc
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp
import ccxt.async_support as ccxt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton state
# ---------------------------------------------------------------------------
_exchange: Optional[ccxt.binanceusdm] = None
_init_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_exchange() -> ccxt.binanceusdm:
    exchange = ccxt.binanceusdm({
        "apiKey": os.getenv("BINANCE_API_KEY", ""),
        "secret": os.getenv("BINANCE_API_SECRET", ""),
        "enableRateLimit": True,
    })
    # ThreadedResolver bypasses aiodns, which fails on some Windows systems.
    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    exchange.session = aiohttp.ClientSession(connector=connector)
    return exchange


def _to_ccxt_symbol(exchange: ccxt.binanceusdm, symbol: str) -> str:
    """Convert Binance symbol ('BTCUSDT') to ccxt format ('BTC/USDT:USDT')."""
    for market_id, market in exchange.markets.items():
        if market.get("id") == symbol:
            return market_id
    if symbol.endswith("USDT"):
        return f"{symbol[:-4]}/USDT:USDT"
    if symbol.endswith("BUSD"):
        return f"{symbol[:-4]}/BUSD:BUSD"
    return symbol


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_exchange() -> ccxt.binanceusdm:
    """Return the shared, fully-initialised exchange instance (init once)."""
    global _exchange
    if _exchange is not None:
        return _exchange
    async with _init_lock:
        if _exchange is not None:
            return _exchange
        ex = _build_exchange()
        logger.info("Loading Binance USD-M Futures markets…")
        try:
            await ex.load_markets()
            logger.info("Markets loaded: %d symbols", len(ex.markets))
            _exchange = ex
        except Exception as e:
            logger.error("Failed to load markets: %s", str(e)[:200])
            raise
    return _exchange


async def reset_exchange() -> None:
    """Close the current exchange session and clear the singleton.

    Call this after rotating API keys so the next ``get_exchange()`` call
    picks up the new values from environment variables without a restart.
    """
    global _exchange
    async with _init_lock:
        if _exchange is not None:
            try:
                await _exchange.close()
            except Exception:
                pass
            _exchange = None
    logger.info("Exchange singleton reset; next call to get_exchange() will reinitialise.")


async def fetch_ticker(symbol: str) -> Dict[str, Any]:
    """Fetch 24-hour price statistics for *symbol* (Binance format, e.g. 'BTCUSDT')."""
    ex = await get_exchange()
    t = await ex.fetch_ticker(_to_ccxt_symbol(ex, symbol))
    return {
        "symbol": symbol,
        "last_price": t.get("last") or t.get("close"),
        "bid": t.get("bid"),
        "ask": t.get("ask"),
        "high_24h": t.get("high"),
        "low_24h": t.get("low"),
        "volume": t.get("baseVolume"),
        "quote_volume": t.get("quoteVolume"),
        "price_change": t.get("change"),
        "price_change_pct": t.get("percentage"),
        "timestamp": datetime.utcnow().isoformat(),
    }


async def fetch_ohlcv(
    symbol: str,
    timeframe: str = "1h",
    limit: int = 500,
    since: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Fetch OHLCV candles for *symbol*.

    Parameters
    ----------
    symbol:    Binance format, e.g. 'BTCUSDT'
    timeframe: ccxt interval string, e.g. '1m', '5m', '1h', '4h', '1d'
    limit:     number of candles (max 1500)
    since:     optional start time as a Unix timestamp in milliseconds
    """
    ex = await get_exchange()
    raw = await ex.fetch_ohlcv(
        _to_ccxt_symbol(ex, symbol),
        timeframe=timeframe,
        since=since,
        limit=min(limit, 1500),
    )
    return [
        {
            "timestamp": datetime.utcfromtimestamp(c[0] / 1000).isoformat(),
            "open": c[1],
            "high": c[2],
            "low": c[3],
            "close": c[4],
            "volume": c[5],
        }
        for c in raw
    ]


async def fetch_order_book(symbol: str, limit: int = 20) -> Dict[str, Any]:
    """Fetch order book snapshot for *symbol* (Binance format, e.g. 'BTCUSDT').

    Returns bids and asks as [[price, quantity], ...] lists, capped at *limit* levels.
    """
    if not 1 <= limit <= 100:
        raise ValueError(f"limit must be between 1 and 100, got {limit}")
    ex = await get_exchange()
    ob = await ex.fetch_order_book(_to_ccxt_symbol(ex, symbol), limit)
    return {
        "symbol": symbol,
        "bids": [[p, q] for p, q in ob["bids"][:limit]],
        "asks": [[p, q] for p, q in ob["asks"][:limit]],
        "timestamp": datetime.utcnow().isoformat(),
    }


async def fetch_futures_symbols() -> List[str]:
    """Return sorted list of all active Binance USD-M perpetual futures symbols."""
    ex = await get_exchange()
    result = [
        market["id"]
        for market in ex.markets.values()
        if market.get("swap")
        and market.get("settle") == "USDT"
        and market.get("active")
        and market.get("id")
    ]
    return sorted(result)


async def fetch_volume_ranked_symbols(top_n: int = 100) -> List[str]:
    """Return up to *top_n* active USD-M perpetual symbols ranked by 24h quote volume.

    Uses a single fetch_tickers() call so it hits the API only once regardless
    of how many symbols exist.
    """
    ex = await get_exchange()
    tickers = await ex.fetch_tickers()
    scored: List[tuple] = []
    for ccxt_sym, ticker in tickers.items():
        market = ex.markets.get(ccxt_sym, {})
        if (
            market.get("swap")
            and market.get("settle") == "USDT"
            and market.get("active")
            and market.get("id")
        ):
            vol = float(ticker.get("quoteVolume") or 0)
            scored.append((market["id"], vol))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [sym for sym, _ in scored[:top_n]]

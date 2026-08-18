import re
from datetime import datetime, timezone

import httpx

_TICKER_RE = re.compile(r"^[A-Za-z]{1,6}(\.[A-Za-z]{1,2})?$")

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
_REQUEST_TIMEOUT_SECONDS = 10.0
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; Groundwork/1.0)"}


class StockDataError(Exception):
    pass


def fetch_ytd_prices(ticker: str) -> dict:
    if not _TICKER_RE.match(ticker):
        raise StockDataError(f"Invalid ticker symbol: {ticker}")

    try:
        response = httpx.get(
            _CHART_URL.format(ticker=ticker.upper()),
            params={"range": "ytd", "interval": "1d"},
            headers=_HEADERS,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as e:
        raise StockDataError(f"Failed to fetch price data for {ticker}: {e}") from e
    except ValueError as e:
        raise StockDataError(f"Received malformed price data for {ticker}: {e}") from e

    points = _parse_chart_payload(payload)
    if len(points) < 2:
        raise StockDataError(f"No YTD price data available for {ticker}")

    first_close = points[0]["close"]
    last_close = points[-1]["close"]
    change_percent = round((last_close - first_close) / first_close * 100, 2)

    resolved_ticker = payload["chart"]["result"][0]["meta"].get("symbol", ticker.upper())

    return {
        "ticker": resolved_ticker,
        "points": points,
        "changePercent": change_percent,
    }


def _parse_chart_payload(payload: dict) -> list[dict]:
    results = payload.get("chart", {}).get("result")
    if not results:
        return []

    result = results[0]
    timestamps = result.get("timestamp") or []
    quotes = result.get("indicators", {}).get("quote") or [{}]
    closes = quotes[0].get("close") or []

    points = []
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        points.append({"date": day, "close": round(float(close), 2)})
    return points

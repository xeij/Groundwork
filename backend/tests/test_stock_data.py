from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.stock_data import fetch_ytd_prices, StockDataError

SAMPLE_PAYLOAD = {
    "chart": {
        "result": [
            {
                "meta": {"symbol": "AAPL"},
                "timestamp": [1767364200, 1786973400],
                "indicators": {"quote": [{"close": [181.5, 196.25]}]},
            }
        ],
        "error": None,
    }
}


def _mock_response(payload: dict, status_ok: bool = True):
    response = MagicMock()
    response.json.return_value = payload
    if status_ok:
        response.raise_for_status.return_value = None
    else:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=MagicMock()
        )
    return response


def test_fetch_ytd_prices_returns_parsed_points():
    with patch("app.services.stock_data.httpx.get", return_value=_mock_response(SAMPLE_PAYLOAD)):
        result = fetch_ytd_prices("aapl")

    assert result["ticker"] == "AAPL"
    assert len(result["points"]) == 2
    assert result["points"][0]["close"] == 181.5
    assert result["changePercent"] == round((196.25 - 181.5) / 181.5 * 100, 2)


def test_fetch_ytd_prices_rejects_invalid_ticker():
    with pytest.raises(StockDataError, match="Invalid ticker"):
        fetch_ytd_prices("../etc/passwd")


def test_fetch_ytd_prices_raises_when_result_is_null():
    not_found_payload = {"chart": {"result": None, "error": {"code": "Not Found"}}}
    with patch("app.services.stock_data.httpx.get", return_value=_mock_response(not_found_payload)):
        with pytest.raises(StockDataError, match="No YTD price data"):
            fetch_ytd_prices("ZZZZ")


def test_fetch_ytd_prices_raises_on_single_point():
    single_point_payload = {
        "chart": {
            "result": [
                {
                    "meta": {"symbol": "AAPL"},
                    "timestamp": [1786973400],
                    "indicators": {"quote": [{"close": [196.25]}]},
                }
            ]
        }
    }
    with patch("app.services.stock_data.httpx.get", return_value=_mock_response(single_point_payload)):
        with pytest.raises(StockDataError, match="No YTD price data"):
            fetch_ytd_prices("aapl")


def test_fetch_ytd_prices_skips_null_closes():
    payload_with_gaps = {
        "chart": {
            "result": [
                {
                    "meta": {"symbol": "AAPL"},
                    "timestamp": [1, 2, 3],
                    "indicators": {"quote": [{"close": [180.0, None, 190.0]}]},
                }
            ]
        }
    }
    with patch("app.services.stock_data.httpx.get", return_value=_mock_response(payload_with_gaps)):
        result = fetch_ytd_prices("aapl")

    assert len(result["points"]) == 2
    assert result["points"][0]["close"] == 180.0
    assert result["points"][1]["close"] == 190.0


def test_fetch_ytd_prices_raises_on_http_error():
    with patch("app.services.stock_data.httpx.get", return_value=_mock_response({}, status_ok=False)):
        with pytest.raises(StockDataError, match="Failed to fetch price data"):
            fetch_ytd_prices("aapl")


def test_fetch_ytd_prices_requests_ytd_range_for_given_ticker():
    with patch("app.services.stock_data.httpx.get", return_value=_mock_response(SAMPLE_PAYLOAD)) as mock_get:
        fetch_ytd_prices("aapl")

    call_kwargs = mock_get.call_args.kwargs
    assert call_kwargs["params"] == {"range": "ytd", "interval": "1d"}
    assert "AAPL" in mock_get.call_args.args[0]

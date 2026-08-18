from fastapi import APIRouter, HTTPException

from ..models import StockChartResponse
from ..services.stock_data import fetch_ytd_prices, StockDataError

router = APIRouter()


@router.get("/stock-chart/{ticker}", response_model=StockChartResponse)
def get_stock_chart(ticker: str):
    try:
        data = fetch_ytd_prices(ticker)
    except StockDataError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return StockChartResponse(**data)

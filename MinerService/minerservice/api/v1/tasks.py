"""Update task endpoints"""

from typing import List

from browserscraper.tasks import update_market_pe_task
from celery import chain
from fastapi import APIRouter
from marketbreadth.tasks import update_spx_market_breadth_task

from ...tasks import (run_hk_daily_updates_task, run_us_daily_updates_task,
                      analyze_wedge_pop_task,
                      update_indicators_for_tickers_task,
                      update_iw_daily_ma_task,
                      update_iwd_tickers_daily_info_task,
                      update_iwd_tickers_info_task, update_iwd_tickers_task,
                      update_iwf_tickers_daily_info_task,
                      update_iwf_tickers_info_task, update_iwf_tickers_task,
                      update_iwm_tickers_daily_info_task,
                      update_iwm_tickers_info_task, update_iwm_tickers_task,
                      update_ndx_intraday_bars_task, update_spx_daily_ma_task,
                      update_spx_intraday_bars_task,
                      update_spx_tickers_daily_info_task,
                      update_spx_tickers_info_task, update_spx_tickers_task,
                      update_tickers_daily_info_task,
                      update_us_trade_calendar_task,
                      update_wedge_pop_for_index_task)

router = APIRouter(prefix='/tasks', tags=['tasks'])


@router.get('/update_us_trade_calendar')
async def update_us_trade_calendar() -> str:
    update_us_trade_calendar_task.delay()
    return 'GOOD'


@router.get('/update_spx_tickers_info')
async def update_spx_tickers_info() -> str:
    chain(update_spx_tickers_task.si(), update_spx_tickers_info_task.si())()
    return 'GOOD'


@router.get('/update_iwd_tickers_info')
async def update_iwd_tickers_info() -> str:
    chain(update_iwd_tickers_task.si(), update_iwd_tickers_info_task.si())()
    return 'GOOD'


@router.get('/update_iwf_tickers_info')
async def update_iwf_tickers_info() -> str:
    chain(update_iwf_tickers_task.si(), update_iwf_tickers_info_task.si())()
    return 'GOOD'


@router.get('/update_iwm_tickers_info')
async def update_iwm_tickers_info() -> str:
    chain(update_iwm_tickers_task.si(), update_iwm_tickers_info_task.si())()
    return 'GOOD'


@router.get('/update_spx_tickers_daily_info')
async def update_spx_tickers_daily_info() -> str:
    update_spx_tickers_daily_info_task.delay()
    return 'GOOD'


@router.get('/update_iwd_tickers_daily_info')
async def update_iwd_tickers_daily_info() -> str:
    update_iwd_tickers_daily_info_task.delay()
    return 'GOOD'


@router.get('/update_iwf_tickers_daily_info')
async def update_iwf_tickers_daily_info() -> str:
    update_iwf_tickers_daily_info_task.delay()
    return 'GOOD'


@router.get('/update_iwm_tickers_daily_info')
async def update_iwm_tickers_daily_info() -> str:
    update_iwm_tickers_daily_info_task.delay()
    return 'GOOD'


@router.post('/update_tickers_daily_info')
async def update_tickers_daily_info(tickers: List[str]) -> str:
    update_tickers_daily_info_task.delay(tickers=tickers)
    return 'GOOD'


@router.get('/update_spx_daily_ma')
async def update_spx_daily_ma() -> str:
    update_spx_daily_ma_task.delay()
    return 'GOOD'


@router.get('/update_iw_daily_ma')
async def update_iw_daily_ma() -> str:
    update_iw_daily_ma_task.delay()
    return 'GOOD'


@router.get('/update_market_pe')
async def update_market_pe() -> str:
    update_market_pe_task.delay()
    return 'GOOD'


@router.get('/update_spx_market_breadth')
async def update_spx_market_breadth() -> str:
    update_spx_market_breadth_task.delay()
    return 'GOOD'


@router.get('/update_wedge_pop_for_index')
async def update_wedge_pop_for_index() -> str:
    update_wedge_pop_for_index_task.delay()
    return 'GOOD'


@router.get('/analyze_wedge_pop')
async def analyze_wedge_pop() -> str:
    analyze_wedge_pop_task.delay()
    return 'GOOD'


@router.get('/update_ndx_intraday_bars')
async def update_ndx_intraday_bars() -> str:
    update_ndx_intraday_bars_task.delay()
    return 'GOOD'


@router.get('/update_spx_intraday_bars')
async def update_spx_intraday_bars() -> str:
    update_spx_intraday_bars_task.delay()
    return 'GOOD'


@router.get('/run_us_daily_updates', description='Update US daily data')
async def run_us_daily_updates() -> str:
    run_us_daily_updates_task.delay()
    return 'GOOD'


@router.get('/run_hk_daily_updates')
async def run_hk_daily_updates() -> str:
    run_hk_daily_updates_task.delay()
    return 'GOOD'


@router.post('/update_indicators_for_tickers')
async def update_indicators_for_tickers(tickers: List[str]) -> str:
    update_indicators_for_tickers_task.delay(tickers=tickers)
    return 'GOOD'

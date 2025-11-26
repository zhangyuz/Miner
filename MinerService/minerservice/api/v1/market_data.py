"""Market data endpoints"""


from fastapi import APIRouter

from ...ws.connection_manager_v2 import get_websocket_manager

router = APIRouter(prefix="/market-data", tags=["market-data"])


@router.get('/realtime/quote/{symbol}')
async def get_realtime_quote(symbol: str):
    """Get real-time quote for a symbol via BarsManager"""
    manager = get_websocket_manager()
    try:
        # Check if manager is available
        if not manager:
            return {'error': 'WebSocket service not initialized', 'details': 'The WebSocket connection manager has not been started'}

        # Check if BarsManager integration is available
        if not manager.bars_manager_integration:
            return {
                'error': 'BarsManager integration not available',
                'details': 'The BarsManager service failed to initialize. This may be due to missing dependencies or configuration issues.',
                'suggestion': 'Check server logs for BarsManager initialization errors and ensure DataMiner package is properly installed.'
            }

        # Sanitize symbol (remove leading $ or other non-alphanumerics except . and =)
        clean_symbol = ''.join(
            ch for ch in symbol if ch.isalnum() or ch in ['.', '='])

        # Get quote from BarsManager integration
        quote_data = await manager.bars_manager_integration.get_initial_quote(clean_symbol)
        if quote_data:
            return quote_data
        else:
            return {'error': f'No quote data available for {clean_symbol}'}

    except Exception as e:
        return {'error': f'Failed to fetch quote for {symbol}: {str(e)}'}


@router.get('/bars/{symbol}/{interval}')
async def get_bars(symbol: str, interval: str = '1m', period: str = '1d'):
    """Get bar data for a symbol with specified interval via BarsManager"""
    manager = get_websocket_manager()
    try:
        # Check if manager is available
        if not manager:
            return {'error': 'WebSocket service not initialized', 'details': 'The WebSocket connection manager has not been started'}

        # Check if BarsManager integration is available
        if not manager.bars_manager_integration:
            return {
                'error': 'BarsManager integration not available',
                'details': 'The BarsManager service failed to initialize. This may be due to missing dependencies or configuration issues.',
                'suggestion': 'Check server logs for BarsManager initialization errors and ensure DataMiner package is properly installed.'
            }

        # Sanitize symbol
        clean_symbol = ''.join(
            ch for ch in symbol if ch.isalnum() or ch in ['.', '='])
        # Validate interval
        allowed_intervals = {
            '1m', '5m', '15m', '30m', '65m',
            '1d', '1wk', '1mo', '3mo'
        }
        if interval not in allowed_intervals:
            return {'error': f'Invalid interval: {interval}'}

        # Get bars from BarsManager integration
        bars_data = await manager.bars_manager_integration.get_initial_bars_snapshot(clean_symbol, interval)
        if bars_data:
            return {
                'symbol': clean_symbol,
                'interval': interval,
                'bars': bars_data
            }
        else:
            return {'error': f'No bars data available for {clean_symbol} {interval}'}

    except Exception as e:
        return {'error': f'Failed to fetch bars for {symbol} {interval}: {str(e)}'}

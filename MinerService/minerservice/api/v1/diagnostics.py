"""Diagnostic and monitoring endpoints"""

from typing import Any, Dict

from fastapi import APIRouter

from ...ws.connection_manager_v2 import get_websocket_manager

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


@router.get('/cleanup_subscriptions')
async def cleanup_subscriptions() -> Dict[str, Any]:
    """Clean up stale subscriptions and return status"""
    manager = get_websocket_manager()
    try:
        if manager:
            await manager.cleanup_stale_subscriptions()
            subscription_status = await manager.get_subscription_status()
            return {
                'status': 'success',
                'message': 'Subscription cleanup completed',
                'subscription_status': subscription_status
            }
        else:
            return {'error': 'Manager not available'}
    except Exception as e:
        return {'error': f'Failed to cleanup subscriptions: {str(e)}'}


@router.get('/cleanup_empty_rooms')
async def cleanup_empty_rooms() -> Dict[str, Any]:
    """Manually trigger cleanup of empty rooms and BarsManager unsubscription"""
    manager = get_websocket_manager()
    try:
        if manager and manager.room_manager:
            cleanup_results = await manager.room_manager.manual_cleanup_empty_rooms()
            return {
                'status': 'success',
                'message': 'Empty room cleanup completed',
                'cleanup_results': cleanup_results
            }
        else:
            return {'error': 'Room manager not available'}
    except Exception as e:
        return {'error': f'Failed to cleanup empty rooms: {str(e)}'}


@router.get('/test_quote_flow_manual/{symbol}')
async def test_quote_flow_manual(symbol: str) -> Dict[str, Any]:
    """Manually test the complete quote flow for a symbol"""
    manager = get_websocket_manager()
    try:
        if not manager:
            return {'error': 'Manager not available'}

        # Step 1: Check if symbol is subscribed
        is_subscribed = symbol.upper() in manager.subscribed_symbols

        # Step 2: Check BarsManager subscription
        bars_manager_subscribed = False
        if manager.bars_manager_integration:
            bars_manager_subscribed = symbol.upper(
            ) in manager.bars_manager_integration.bars_manager.subscribed_tickers

        # Step 3: Check Redis for active quotes
        redis_client = await manager.get_redis()
        active_quotes = await redis_client.smembers('quotes:active')
        active_quotes = [
            q.decode('utf-8') if isinstance(q, bytes) else q for q in active_quotes]

        # Step 4: Check latest quote in Redis
        latest_quote_key = f'quote:latest:{symbol.upper()}'
        latest_quote = await redis_client.get(latest_quote_key)

        # Step 5: Check Redis subscription service health
        redis_service_health = None
        if manager.redis_subscription_service:
            redis_service_health = manager.redis_subscription_service.get_health_status()

        # Step 6: Try to get initial quote
        initial_quote = None
        if manager.bars_manager_integration:
            initial_quote = await manager.bars_manager_integration.get_initial_quote(symbol)

        return {
            'symbol': symbol.upper(),
            'test_results': {
                'websocket_subscribed': is_subscribed,
                'bars_manager_subscribed': bars_manager_subscribed,
                'redis_active_quotes': active_quotes,
                'redis_latest_quote_available': latest_quote is not None,
                'redis_latest_quote_data': latest_quote.decode('utf-8') if latest_quote else None,
                'initial_quote_available': initial_quote is not None,
                'initial_quote_data': initial_quote
            },
            'redis_service_health': redis_service_health,
            'diagnosis': {
                'issue': 'quote_flow_breakdown' if not is_subscribed or not bars_manager_subscribed else 'redis_subscription_issue' if not redis_service_health.get('running', False) else 'data_flow_issue',
                'recommendation': 'Check subscription flow' if not is_subscribed else 'Check BarsManager integration' if not bars_manager_subscribed else 'Check Redis subscription service' if not redis_service_health.get('running', False) else 'Check data flow from BarsManager to Redis'
            }
        }
    except Exception as e:
        return {'error': f'Failed to test quote flow: {str(e)}'}


@router.get('/redis_service_health')
async def redis_service_health() -> Dict[str, Any]:
    """Get health status of Redis subscription service"""
    manager = get_websocket_manager()
    try:
        if not manager or not manager.redis_subscription_service:
            return {'error': 'Redis subscription service not available'}

        health = manager.redis_subscription_service.get_health_status()
        return {
            'status': 'success',
            'health': health
        }
    except Exception as e:
        return {'error': f'Failed to get health status: {str(e)}'}


@router.post('/refresh_redis_subscriptions')
async def refresh_redis_subscriptions() -> Dict[str, Any]:
    """Manually refresh Redis subscriptions"""
    manager = get_websocket_manager()
    try:
        if not manager or not manager.redis_subscription_service:
            return {'error': 'Redis subscription service not available'}

        # Refresh subscriptions
        await manager.redis_subscription_service.refresh_subscriptions()

        # Get updated health status
        health = manager.redis_subscription_service.get_health_status()

        return {
            'status': 'success',
            'message': 'Redis subscriptions refreshed',
            'health': health
        }
    except Exception as e:
        return {'error': f'Failed to refresh subscriptions: {str(e)}'}


@router.get('/debug_redis_subscriptions')
async def debug_redis_subscriptions() -> Dict[str, Any]:
    """Debug Redis subscription service status"""
    manager = get_websocket_manager()
    try:
        if not manager or not manager.redis_subscription_service:
            return {'error': 'Redis subscription service not available'}

        # Get detailed subscription status
        status = await manager.redis_subscription_service.debug_subscription_status()

        # Also check BarsManager integration status
        bars_manager_status = None
        if manager.bars_manager_integration:
            bars_manager_status = manager.bars_manager_integration.get_active_subscriptions()

        return {
            'status': 'success',
            'redis_subscription_service': status,
            'bars_manager_integration': bars_manager_status,
            'websocket_connections': len(manager.local_connections),
            'websocket_subscribed_symbols': list(manager.subscribed_symbols),
            'websocket_subscribed_bars': [f"{ticker}:{interval}" for ticker, interval in manager.subscribed_bars]
        }
    except Exception as e:
        return {'error': f'Failed to get debug status: {str(e)}'}


@router.post('/force_redis_resubscribe')
async def force_redis_resubscribe() -> Dict[str, Any]:
    """Force Redis subscription service to resubscribe to all channels"""
    manager = get_websocket_manager()
    try:
        if not manager or not manager.redis_subscription_service:
            return {'error': 'Redis subscription service not available'}

        # Force resubscribe
        await manager.redis_subscription_service.force_resubscribe()

        # Get updated status
        status = await manager.redis_subscription_service.debug_subscription_status()

        return {
            'status': 'success',
            'message': 'Redis subscriptions refreshed',
            'updated_status': status
        }
    except Exception as e:
        return {'error': f'Failed to force resubscribe: {str(e)}'}


@router.get('/verify_cleanup_integrity')
async def verify_cleanup_integrity() -> Dict[str, Any]:
    """Verify the overall integrity of the cleanup system"""
    manager = get_websocket_manager()
    try:
        if not manager:
            return {'error': 'WebSocket manager not available'}

        # Perform comprehensive cleanup integrity verification
        verification_results = await manager.verify_cleanup_integrity()

        return {
            'status': 'success',
            'verification_results': verification_results
        }
    except Exception as e:
        return {'error': f'Failed to verify cleanup integrity: {str(e)}'}


@router.post('/force_cleanup_disconnected')
async def force_cleanup_disconnected() -> Dict[str, Any]:
    """Force cleanup of all disconnected clients and stale data"""
    manager = get_websocket_manager()
    try:
        if not manager:
            return {'error': 'WebSocket manager not available'}

        # Get current status before cleanup
        before_cleanup = await manager.verify_cleanup_integrity()

        # Trigger comprehensive cleanup
        await manager.cleanup_stale_subscriptions()

        # Get status after cleanup
        after_cleanup = await manager.verify_cleanup_integrity()

        return {
            'status': 'success',
            'message': 'Forced cleanup completed',
            'before_cleanup': before_cleanup,
            'after_cleanup': after_cleanup,
            'cleanup_summary': {
                'before_status': before_cleanup.get('overall_status'),
                'after_status': after_cleanup.get('overall_status'),
                'improvement': before_cleanup.get('overall_status') != after_cleanup.get('overall_status')
            }
        }
    except Exception as e:
        return {'error': f'Failed to force cleanup: {str(e)}'}

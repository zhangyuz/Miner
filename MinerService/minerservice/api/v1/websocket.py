"""WebSocket management endpoints"""

from typing import Any, Dict, Optional

from fastapi import APIRouter

from ...ws.connection_manager_v2 import get_websocket_manager

router = APIRouter(prefix="/websocket", tags=["websocket"])


@router.get('/status')
async def get_websocket_status():
    """Get WebSocket service status and connection information"""
    manager = get_websocket_manager()
    if not manager:
        return {'status': 'unavailable', 'message': 'WebSocket service not initialized'}

    try:
        # Get basic status
        status = {
            'status': 'healthy',
            'process': {
                'process_id': manager.process_id,
                'local_connections': len(manager.local_connections),
                'total_connections': await manager.get_total_connections(),
                'subscribed_symbols': list(manager.subscribed_symbols),
                'running': manager.running
            },
            'redis': await manager.get_redis_status()
        }

        # Add RedisSubscriptionService status if available
        if manager.redis_subscription_service:
            redis_service_status = {
                'running': manager.redis_subscription_service.running,
                'active_quote_subscriptions': list(manager.redis_subscription_service.active_quote_subscriptions),
                'active_bar_subscriptions': list(manager.redis_subscription_service.active_bar_subscriptions),
                'pubsub_ready': manager.redis_subscription_service.pubsub is not None
            }
            status['redis_subscription_service'] = redis_service_status

        # Add RoomManager status if available
        if manager.room_manager:
            room_manager_status = manager.room_manager.get_local_room_stats()
            status['room_manager'] = room_manager_status

        return status

    except Exception as e:
        return {'status': 'error', 'message': str(e)}


@router.get('/connections')
async def get_websocket_connections():
    """Get all active WebSocket connections across all processes"""
    manager = get_websocket_manager()
    if not manager:
        return {'connections': []}

    try:
        redis_client = await manager.get_redis()
        connection_keys = await redis_client.keys('websocket:connections:*')

        connections = []
        for key in connection_keys:
            try:
                client_id = key.split(':')[-1]
                connection_data = await redis_client.hgetall(key)
                if connection_data:
                    connections.append({
                        'client_id': client_id,
                        'process_id': connection_data.get('process_id'),
                        'connected_at': connection_data.get('connected_at'),
                        'last_heartbeat': connection_data.get('last_heartbeat')
                    })
            except Exception as e:
                print(f"Error getting connection data for {key}: {e}")

        return {'connections': connections}
    except Exception as e:
        return {'error': str(e), 'connections': []}


@router.get('/rooms')
async def get_websocket_rooms():
    """Get all active WebSocket rooms"""
    manager = get_websocket_manager()
    if not manager:
        return {'rooms': []}

    try:
        rooms = await manager.list_rooms()
        return {'rooms': rooms}
    except Exception as e:
        return {'error': str(e), 'rooms': []}


@router.get('/rooms/{room_id}')
async def get_room_info(room_id: str):
    """Get information about a specific room"""
    manager = get_websocket_manager()
    if not manager:
        return {'error': 'WebSocket service not available'}

    try:
        room_info = await manager.get_room_info(room_id)
        if room_info:
            return room_info
        else:
            return {'error': f'Room {room_id} not found'}
    except Exception as e:
        return {'error': str(e)}


@router.post('/rooms/{room_id}/join')
async def join_room(room_id: str, client_id: str):
    """Join a client to a room"""
    manager = get_websocket_manager()
    if not manager:
        return {'error': 'WebSocket service not available'}

    try:
        success = await manager.join_room(client_id, room_id)
        if success:
            return {'status': 'success', 'message': f'Client {client_id} joined room {room_id}'}
        else:
            return {'error': f'Failed to join room {room_id}'}
    except Exception as e:
        return {'error': str(e)}


@router.post('/rooms/{room_id}/leave')
async def leave_room(room_id: str, client_id: str):
    """Remove a client from a room"""
    manager = get_websocket_manager()
    if not manager:
        return {'error': 'WebSocket service not available'}

    try:
        success = await manager.leave_room(client_id, room_id)
        if success:
            return {'status': 'success', 'message': f'Client {client_id} left room {room_id}'}
        else:
            return {'error': f'Failed to leave room {room_id}'}
    except Exception as e:
        return {'error': str(e)}


@router.post('/rooms/{room_id}/broadcast')
async def broadcast_to_room(room_id: str, message: str, exclude_client: Optional[str] = None):
    """Broadcast a message to all clients in a room"""
    manager = get_websocket_manager()
    if not manager:
        return {'error': 'WebSocket service not available'}

    try:
        client_count = await manager.broadcast_to_room(room_id, message, exclude_client)
        return {
            'status': 'success',
            'message': f'Message broadcasted to {client_count} clients in room {room_id}'
        }
    except Exception as e:
        return {'error': str(e)}


@router.get('/clients/{client_id}/rooms')
async def get_client_rooms(client_id: str):
    """Get all rooms a client is in"""
    manager = get_websocket_manager()
    if not manager:
        return {'rooms': []}

    try:
        rooms = await manager.get_client_rooms(client_id)
        return {'client_id': client_id, 'rooms': list(rooms)}
    except Exception as e:
        return {'error': str(e), 'rooms': []}


@router.post('/broadcast')
async def broadcast_message(message: str):
    """Broadcast a message to all WebSocket clients"""
    manager = get_websocket_manager()
    if not manager:
        return {'error': 'WebSocket service not available'}

    try:
        await manager.broadcast_to_all_processes(message)
        return {'status': 'success', 'message': 'Message broadcasted'}
    except Exception as e:
        return {'error': str(e)}


@router.post('/cleanup_disconnected')
async def cleanup_disconnected_clients() -> Dict[str, Any]:
    """Manually trigger cleanup of disconnected clients and stale data"""
    manager = get_websocket_manager()
    if not manager:
        return {'error': 'WebSocket service not available'}

    try:
        # Get current connection status
        before_cleanup = {
            'local_connections': len(manager.local_connections),
            'total_connections': await manager.get_total_connections(),
            'rooms': await manager.list_rooms() if manager.room_manager else []
        }

        # Trigger cleanup
        await manager.cleanup_stale_subscriptions()

        # Get room manager stats if available
        room_stats = None
        if manager.room_manager:
            room_stats = manager.room_manager.get_local_room_stats()

        # Get after cleanup status
        after_cleanup = {
            'local_connections': len(manager.local_connections),
            'total_connections': await manager.get_total_connections(),
            'rooms': await manager.list_rooms() if manager.room_manager else []
        }

        return {
            'status': 'success',
            'message': 'Cleanup completed',
            'before_cleanup': before_cleanup,
            'after_cleanup': after_cleanup,
            'room_manager_stats': room_stats,
            'cleanup_summary': {
                'connections_removed': before_cleanup['total_connections'] - after_cleanup['total_connections'],
                'rooms_affected': len(before_cleanup['rooms']) - len(after_cleanup['rooms'])
            }
        }

    except Exception as e:
        return {'error': f'Failed to cleanup disconnected clients: {str(e)}'}

import asyncio
import json
import logging
from contextlib import asynccontextmanager, suppress
from typing import Optional

# yfinance import removed - using BarsManager integration only
from detonator import get_logger, is_prod
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .api.v1 import api_v1_router
from .services.vegas_tunnel_integration import VegasTunnelIntegration
from .utils import send_message
from .ws.connection_manager_v2 import (WebSocketConnectionManager, WsMsgTypes,
                                       get_websocket_manager)

_logger = get_logger('MinerService', logging.DEBUG)

manager: Optional[WebSocketConnectionManager] = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Lifespan context manager for FastAPI startup/shutdown events"""
    global manager

    # Startup
    manager = get_websocket_manager()
    await manager.startup()

    # Start background tasks
    monitoring_task = asyncio.create_task(monitor_running_status())

    # Vegas Tunnel (prod only)
    vegas_tunnel_integration = None
    if is_prod():
        vegas_tunnel_integration = VegasTunnelIntegration()
        vegas_tunnel_integration.start()

    yield

    # Shutdown: stop Vegas tunnel first so scheduler thread exits cleanly
    if vegas_tunnel_integration is not None:
        vegas_tunnel_integration.stop()

    if monitoring_task:
        monitoring_task.cancel()
        with suppress(asyncio.CancelledError):
            await monitoring_task
    await manager.shutdown()


app = FastAPI(lifespan=lifespan)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API v1 router with all organized endpoints
app.include_router(api_v1_router)


async def handle_subscribe(websocket: WebSocket, client_id: str, message):
    symbol = message.get('symbol')
    if not symbol.strip():
        await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_ERROR, {
            'message': f'Invalid symbol for subscription:"{symbol}"',
        })
        return

    symbol = symbol.strip().upper().replace('.', '_')

    try:
        room_id = await manager.subscribe_symbol(symbol, client_id)

        if not room_id:
            await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_ERROR, {
                'message': f'Failed to subscribe:"{symbol}"',
            })
            return

        await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_SUBSCRIBED, {
            'symbol': symbol,
            'room_id': room_id,
            'message': f'Subscribed to {symbol} quotes and joined room {room_id}',
        })
        _logger.info(
            f"Client {client_id} subscribed to {symbol} quotes and joined room {room_id}")
        # Send initial quote data
        try:
            quote_data = await manager.bars_manager_integration.get_initial_quote(symbol)
            if quote_data:
                if quote_data.get('status') == 'subscribed_waiting_for_data':
                    await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_SUBSCRIBED, {
                        'symbol': symbol,
                        'message': f'{symbol} subscribed to live quotes, waiting for data...',
                    })
                else:
                    await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_QUOTE_UPDATE, {
                        'data': quote_data,
                    })
            else:
                await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_ERROR, {
                    'message': f'No quote data available for {symbol}',
                })
        except Exception as e:
            _logger.error(
                f"Error sending initial quote for {symbol}: {e}")

    except Exception as e:
        _logger.error(
            f"Error subscribing to symbol {symbol}: {e}")
        await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_ERROR, {
            'message': f'Failed to subscribe to {symbol}: {str(e)}',
        })


async def handle_subscribe_bars(websocket: WebSocket, client_id: str, message):
    symbol = message.get('symbol')
    interval = message.get('interval')

    if not symbol or not interval:
        await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_ERROR, {
            'message': 'Both symbol and interval are required for bars subscription',
        })
        return

    # Validate symbol and interval
    if not isinstance(symbol, str) or len(symbol.strip()) == 0:
        await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_ERROR, {
            'message': 'Invalid symbol format',
        })
        return

    symbol = symbol.strip().upper()

    # Validate interval
    allowed_intervals = {'1m', '5m', '15m',
                         '30m', '65m', '1d', '1wk', '1mo', '3mo'}
    if interval not in allowed_intervals:
        await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_ERROR, {
            'message': f'Invalid interval: {interval}. Allowed: {", ".join(sorted(allowed_intervals))}',
        })
        return

    try:
        room_id = await manager.subscribe_bars(symbol, interval, client_id)

        if not room_id:
            await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_ERROR, {
                'message': f'Failed to subscribe to {symbol}: {interval}',
            })
            return
        else:
            await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_BARS_SUBSCRIBED, {
                'symbol': symbol,
                'interval': interval,
                'room_id': room_id,
                'message': f'Subscribed to {symbol} {interval} bars and joined room {room_id}',
            })
            _logger.info(
                f"Client {client_id} subscribed to {symbol} {interval} bars and joined room {room_id}")
        # Send initial bars data
        try:
            bars_data = await manager.bars_manager_integration.get_initial_bars_snapshot(symbol,
                                                                                         interval)
            if bars_data:
                await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_BARS, {
                    'data': {
                        'symbol': symbol,
                        'interval': interval,
                        'bars': bars_data,
                        'is_snapshot': True
                    },
                })
            else:
                await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_ERROR, {
                    'message': f'No bars data available for {symbol} {interval}',
                })
        except Exception as e:
            _logger.error(
                f"Error sending initial bars for {symbol} {interval}: {e}")

    except Exception as e:
        _logger.error(
            f"Error subscribing to bars for {symbol} {interval}: {e}")
        await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_ERROR, {
            'message': f'Failed to subscribe to bars for {symbol} {interval}: {str(e)}',
        })


async def handle_unsubscribe(websocket: WebSocket, client_id: str, message):
    symbol = message.get('symbol')
    if not symbol:
        await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_ERROR, {
            'message': 'Symbol is required for unsubscription',
        })
        return

    symbol = symbol.strip().upper().replace('.', '-')

    try:
        await manager.unsubscribe_symbol(symbol, client_id)
        await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_UNSUBSCRIBED, {
            'symbol': symbol,
        })
        _logger.info(f"Unsubscribed {client_id} from {symbol}")
    except Exception as e:
        _logger.error(
            f"Error unsubscribing from symbol {symbol}: {e}")
        await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_ERROR, {
            'message': f'Failed to unsubscribe from {symbol}: {str(e)}',
        })


async def handle_unsubscribe_bars(websocket: WebSocket, client_id: str, message):
    symbol = message.get('symbol')
    interval = message.get('interval')

    if not symbol or not interval:
        await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_ERROR, {
            'message': 'Both symbol and interval are required for bars unsubscription',
        })
        return

    symbol = symbol.strip().upper().replace('.', '-')

    try:
        await manager.unsubscribe_bars(symbol, interval, client_id)
        await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_BARS_UNSUBSCRIBED, {
            'symbol': symbol,
            'interval': interval,
        })
        _logger.info(
            f"Unsubscribed {client_id} from {symbol} {interval} bars")
    except Exception as e:
        _logger.error(
            f"Error unsubscribing from bars for {symbol} {interval}: {e}")
        await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_ERROR, {
            'message': f'Failed to unsubscribe from bars for {symbol} {interval}: {str(e)}',
        })


async def handle_room_broadcast(websocket: WebSocket, client_id: str, message):
    room_id = message.get('room_id')
    room_message = message.get('message')
    if not room_id or not room_message:
        await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_ERROR, {
            'message': 'Room ID and message are required for room broadcast',
        })

    try:
        client_count = await manager.broadcast_to_room(room_id, room_message, exclude_client=client_id)
        await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_ROOM_BROADCAST_SENT, {
            'room_id': room_id,
            'client_count': client_count,
        })
        _logger.info(
            f"Room broadcast sent to {client_count} clients in room {room_id}")
    except Exception as e:
        _logger.error(
            f"Error broadcasting to room {room_id}: {e}")
        await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_ERROR, {
            'message': f'Failed to broadcast to room {room_id}: {str(e)}',
        })


async def handle_get_rooms(websocket: WebSocket, client_id: str, _):
    try:
        rooms = await manager.get_client_rooms(client_id)
        await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_CLIENT_ROOMS, {
            'rooms': list(rooms),
        })
    except Exception as e:
        _logger.error(
            f"Error getting rooms for client {client_id}: {e}")
        await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_ERROR, {
            'message': f'Failed to get rooms: {str(e)}',
        })


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """WebSocket endpoint for real-time communication with BarsManager integration"""
    try:
        await manager.connect(websocket, client_id)
        _logger.info(f"WebSocket client connected: {client_id}")

        # Send welcome message
        await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_CONNECTED, {
            'client_id': client_id,
            'message': 'Connected to WebSocket service with BarsManager integration',
        })

        while True:
            try:
                data = await websocket.receive_text()
                message = json.loads(data)
                _logger.info(f"Received message: {message}")

                if message.get('type') == WsMsgTypes.WS_MSG_TYPE_SUBSCRIBE:
                    await handle_subscribe(websocket, client_id, message)
                elif message.get('type') == WsMsgTypes.WS_MSG_TYPE_SUBSCRIBE_BARS:
                    await handle_subscribe_bars(websocket, client_id, message)
                elif message.get('type') == WsMsgTypes.WS_MSG_TYPE_UNSUBSCRIBE:
                    await handle_unsubscribe(websocket, client_id, message)
                elif message.get('type') == WsMsgTypes.WS_MSG_TYPE_UNSUBSCRIBE_BARS:
                    await handle_unsubscribe_bars(websocket, client_id, message)
                elif message.get('type') == WsMsgTypes.WS_MSG_TYPE_PING:
                    await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_PONG, {
                    })

                elif message.get('type') == WsMsgTypes.WS_MSG_TYPE_ROOM_BROADCAST:
                    await handle_room_broadcast(websocket, client_id, message)
                elif message.get('type') == WsMsgTypes.WS_MSG_TYPE_GET_ROOMS:
                    await handle_get_rooms(websocket, client_id, message)
                else:
                    # Unknown message type
                    await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_ERROR, {
                        'message': f'Unknown message type: {message.get("type")}',
                    })

            except json.JSONDecodeError:
                await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_ERROR, {
                    'message': 'Invalid JSON format',
                })
            except Exception as e:
                _logger.error(
                    f"Error processing message from {client_id}: {e}")
                await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_ERROR, {
                    'message': f'Internal server error: {str(e)}',
                })

    except WebSocketDisconnect:
        _logger.info(f"WebSocket client disconnected: {client_id}")
    except Exception as e:
        _logger.error(f"WebSocket error for {client_id}: {e}")
        # Try to send error message before closing
        try:
            await send_message(websocket, client_id, WsMsgTypes.WS_MSG_TYPE_ERROR, {
                'message': f'Connection error: {e}',
            })
        except:
            pass  # Ignore errors when sending error message
    finally:
        _logger.info(
            f"🔄 Starting cleanup for disconnected client: {client_id}")
        try:
            # Comprehensive cleanup through the manager
            await manager.disconnect(websocket, client_id)
            _logger.info(f"✅ Cleanup completed for client: {client_id}")
        except Exception as e:
            _logger.error(
                f"❌ Error during disconnect cleanup for {client_id}: {e}")
            # Try to force cleanup even if manager fails
            try:
                if websocket:
                    await websocket.close()
            except:
                pass


async def monitor_running_status():
    """Monitor and broadcast real-time bars updates for subscribed symbols"""
    _logger.info("Starting bars monitoring service...")
    while True:
        try:
            _logger.debug(manager.dump())
            # Wait before next status check
            await asyncio.sleep(60 * 60)  # Check status every 30 seconds
        except Exception as e:
            _logger.error(f"Error in bars monitoring: {e}")
            await asyncio.sleep(60)  # Wait longer on error

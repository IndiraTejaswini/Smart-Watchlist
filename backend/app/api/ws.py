"""WebSocket quote gateway endpoint."""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.analytics.constants import WS_MAX_SUBSCRIPTIONS_PER_CLIENT
from app.analytics.streaming.gateway import WebSocketGateway

router = APIRouter(tags=["websocket"])
gateway = WebSocketGateway()


@router.websocket("/ws/quotes")
async def quotes_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    session = await gateway.register(websocket)
    writer = asyncio.create_task(gateway.client_writer(session))
    try:
        while True:
            command = await websocket.receive_json()
            action = command.get("action")
            symbols = {
                str(symbol).strip().upper()
                for symbol in command.get("symbols", [])
                if str(symbol).strip()
            }
            if action == "subscribe":
                requested = session.subscribed_symbols | symbols
                if len(requested) > WS_MAX_SUBSCRIPTIONS_PER_CLIENT:
                    await websocket.send_json(
                        {"error": "Maximum subscriptions per client exceeded"}
                    )
                    continue
                await gateway.subscribe(session, symbols)
            elif action == "unsubscribe":
                await gateway.unsubscribe(session, symbols)
            elif action == "ping":
                await websocket.send_json({"action": "pong"})
            elif action == "resync":
                await gateway.resync(session)
    except WebSocketDisconnect:
        pass
    finally:
        writer.cancel()
        try:
            await writer
        except asyncio.CancelledError:
            pass
        await gateway.disconnect(session)

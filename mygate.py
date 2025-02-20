import asyncio
import aiohttp
import json
import time
import uuid
import hmac
import hashlib
import cloudscraper
from loguru import logger

TOKEN_FILE = "token.txt"
BASE_URL = "https://api.mygate.network/api/front"
WS_URL = "wss://api.mygate.network/socket.io/"
SECRET_KEY = "|8S%QN9v&/J^Za"

async def read_token():
    try:
        with open(TOKEN_FILE, "r") as file:
            return file.readline().strip()
    except FileNotFoundError:
        logger.error("Token file not found!")
        return None

def generate_signature(node_id):
    timestamp = str(int(time.time() * 1000))
    message = f"{node_id}:{timestamp}"
    signature = hmac.new(SECRET_KEY.encode(), message.encode(), hashlib.sha256).hexdigest()
    return signature, timestamp

async def get_user_nodes(session, token):
    headers = {"Authorization": f"Bearer {token}"}
    async with session.get(f"{BASE_URL}/nodes?limit=10&page=1", headers=headers) as resp:
        if resp.status == 200:
            data = await resp.json()
            return [item['id'] for item in data.get('data', {}).get('items', [])]
        elif resp.status == 401:
            logger.error("Unauthorized! Please update your token.")
            return None
        return []

async def register_node(session, token):
    headers = {"Authorization": f"Bearer {token}"}
    node_id = str(uuid.uuid4())
    payload = {"id": node_id, "status": "Good", "activationDate": time.strftime('%Y-%m-%dT%H:%M:%SZ')}
    async with session.post(f"{BASE_URL}/nodes", json=payload, headers=headers) as resp:
        if resp.statusCode == 200:
            logger.info("Node registered successfully.")
            return node_id
        logger.error("Failed to register node.")
        return None


async def get_quests_list(session, token):
    headers = {"Authorization": f"Bearer {token}"}
    async with session.get(f"{BASE_URL}/achievements/ambassador", headers=headers) as resp:
        if resp.status == 200:
            data = await resp.json()
            return [item['_id'] for item in data.get('data', {}).get('items', []) if item['status'] == "UNCOMPLETED"]
        return []

async def submit_quest(session, token, quest_id):
    headers = {"Authorization": f"Bearer {token}"}
    async with session.post(f"{BASE_URL}/achievements/ambassador/{quest_id}/submit?", headers=headers) as resp:
        logger.info("Submit quest response:", await resp.json())

async def get_user_info(session, token):
    headers = {"Authorization": f"Bearer {token}"}
    async with session.get(f"{BASE_URL}/users/me", headers=headers) as resp:
        if resp.status == 200:
            data = await resp.json()
            return data.get('data', {})
        return {}

async def check_quests(session, token):
    logger.info("Checking for new quests...")
    quest_ids = await get_quests_list(session, token)
    if quest_ids:
        logger.info(f"Found {len(quest_ids)} new uncompleted quests.")
        for quest_id in quest_ids:
            await submit_quest(session, token, quest_id)
            logger.info(f"Quest {quest_id} completed successfully.")
    else:
        logger.info("No new uncompleted quests found.")

async def connect_websocket(token, node_id):
    signature, timestamp = generate_signature(node_id)
    ws_url = f"{WS_URL}?nodeId={node_id}&signature={signature}&timestamp={timestamp}&version=2&EIO=4&transport=websocket"
    headers = {
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
        "Cache-Control": "no-cache",
        "Connection": "Upgrade",
        "Host": "api.mygate.network",
        "Origin": "chrome-extension://hajiimgolngmlbglaoheacnejbnnmoco",
        "Pragma": "no-cache",
        "Sec-WebSocket-Extensions": "permessage-deflate; client_max_window_bits",
        "Upgrade": "websocket",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Authorization": f"Bearer {token}"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(ws_url, headers=headers) as ws:
                logger.info(f"Connected to WebSocket for Node {node_id}")
                user_info = await get_user_info(session, token)
                current_point = user_info.get("currentPoint", 0)
                logger.info(f"Current Points: {current_point}")
                await ws.send_str(f"40{{\"token\":\"Bearer {token}\"}}")
                while True:
                    msg = await ws.receive()
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        if msg.data in ["2", "41"]:
                            logger.info(f"Sending Ping message... KEEP ALIVE")
                            await ws.send_str("3") 
                        else:
                            logger.info(f"Message from {node_id}: {msg.data}")
                    elif msg.type in [aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR]:
                        logger.warning(f"WebSocket closed or error for Node {node_id}, reconnecting...")
                        break
    except Exception as e:
        logger.error(f"WebSocket error: {e}, reconnecting...")
    await asyncio.sleep(5)
    await connect_websocket(token, node_id)

async def main():
    token = await read_token()
    if not token:
        logger.error("No token found. Exiting.")
        return
    async with aiohttp.ClientSession() as session:
        nodes = await get_user_nodes(session, token)
        logger.info(f"Active user nodes: {nodes}")
        if nodes is None:
            return
        if not nodes:
            logger.info("No nodes found, registering new node...")
            node_id = await register_node(session, token)
            if node_id:
                nodes = [node_id]
        node_id = nodes[0]
        asyncio.create_task(connect_websocket(token, node_id))
        asyncio.create_task(check_quests(session, token))
        while True:
            await asyncio.sleep(3600)  # Keep bot running

if __name__ == "__main__":
    asyncio.run(main())

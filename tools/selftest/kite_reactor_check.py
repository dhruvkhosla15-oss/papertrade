"""Zerodha price connection after a refused login (24 Nov 2026): with the library's background loop idle, a new
connection opened from another thread was never picked up; handed to the loop it is. Prints KITE-REACTOR OK/BAD."""
import asyncio, threading, time, sys, logging
import os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
logging.basicConfig(level=logging.CRITICAL)
import websockets
conns = []
async def handler(ws, *a):
    conns.append(time.time())
    try:
        await ws.wait_closed()
    except Exception:
        pass
def server():
    async def main():
        async with websockets.serve(handler, "127.0.0.1", 9911):
            await asyncio.Future()
    asyncio.run(main())
threading.Thread(target=server, daemon=True).start(); time.sleep(1)
from kiteconnect import KiteTicker
from app.feed.kite import _in_reactor
def mk():
    return KiteTicker("k", "t", root="ws://127.0.0.1:9911", reconnect=True)
t1 = mk(); t1.connect(threaded=True); time.sleep(2); print("first connection:", len(conns))
_in_reactor(t1.close); time.sleep(3)                     # like the refusal at 7:06: retries stopped, loop idle
n = len(conns)
def old_way():
    t = mk(); t.connect(threaded=True)
threading.Thread(target=old_way).start(); time.sleep(8)
print("old way, new connection opened from another thread:", len(conns) - n)
n = len(conns)
def new_way():
    t = mk(); _in_reactor(t.connect, True)
threading.Thread(target=new_way).start(); time.sleep(5)
got = len(conns) - n
print("new way (handed to the loop):", got)
print("KITE-REACTOR", "OK" if got >= 1 else "BAD")

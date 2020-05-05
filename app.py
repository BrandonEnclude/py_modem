import asyncio
import websockets, ssl
import pathlib
import json
from modem import SIMS
import time
import os

URI = os.environ.get('WEBSOCKET_URI')
WS_KEY = os.environ.get('WS_KEY')
RECONNECT_DELAY = int(os.environ.get('RECONNECT_DELAY', 3))

ssl_context = ssl.SSLContext()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE
headers={'ws-key': WS_KEY}

class App:
    def __init__(self, URI, debug = False):
        # Setup app and websocket
        self.URI = URI
        self.sims = None
        self.websocket = None

    async def listen(self):
        try:
            async with websockets.connect(self.URI, ssl = ssl_context, extra_headers=headers) as websocket:
                self.websocket = websocket
                while True:
                    msg = await websocket.recv()
                    await self._on_message(msg)
        except websockets.ConnectionClosed as e:
            await self._teardown_and_rebuild()

    async def _on_message(self, msg):
        jsonrpc = json.loads(msg)
        namespace, method_name, params = self._extract_params(jsonrpc)
        if method_name is not None:
            method = getattr(self, method_name)
            await method(**params)

    async def _teardown_and_rebuild(self, delay = RECONNECT_DELAY):
        try:
            await self.sims.close_all()
        except:
            pass
        await asyncio.sleep(delay)
        try:
            await self.listen()
        except RecursionError:
            pass
        except Exception as e:
            #TODO: log error
            print(repr(e), flush=True)
            await self._teardown_and_rebuild()

    def _extract_params(self, jsonrpc):
        if jsonrpc.get('result') is None and jsonrpc.get('method') is None:
            return None, None, None
        method_name = jsonrpc['result']['method'] if 'result' in jsonrpc.keys() else jsonrpc['method']
        namespace, method_name = method_name.split('.')
        if method_name.startswith('_') or method_name == 'start':
            raise Exception('Cannot access private methods')
        params = jsonrpc['result']['params'] if 'result' in jsonrpc.keys() else jsonrpc['params']
        return namespace, method_name, params

    ### SIM Methods ###
    async def available_sims(self, sims):
        self.sims = SIMS(json.loads(sims), self.websocket)
        try:
            await self._connect_sims()
            await self.sim_status()
        except Exception as e:
            print(repr(e), flush=True)

    async def _connect_sims(self):
        await self.sims.connect_all()
        await self.sims.get_stored_messages()

    async def sim_status(self, id = None):
        id = id if id is not None else int(time.time())
        await self.websocket.send(json.dumps({'id': id, 'jsonrpc':'2.0','method':'sms_server.broadcast_sim_status','params':{'id': id, 'sims': self.sims.to_dict()}}))

    async def send_sms(self, id, msg, sim_number, recipient_number):
        try:
            await self.sims.send_sms(id, msg, sim_number, recipient_number)
        except Exception as e:
            await self.websocket.send(json.dumps({'id': id, 'jsonrpc':'2.0','method':'sms_server.sent_status','params':{'id': id, 'message': f'ERR: {repr(e)}'}}))
        else:
            await self.websocket.send(json.dumps({'id': id, 'jsonrpc':'2.0','method':'sms_server.sent_status','params':{'id': id, 'message': 'Sent'}}))

    async def delete_stored_sms(self, sim_number, msg_index):
        await self.sims.delete_stored_sms(sim_number, msg_index)

    async def reconnect(self, id):
        try:
            await self._teardown_and_rebuild(3)
        except Exception as e:
            await self.websocket.send(json.dumps({'id': id, 'jsonrpc':'2.0','method':'sms_server.reconnect_done','params':{'id': id, 'status': repr(e)}}))
        await self.websocket.send(json.dumps({'id': id, 'jsonrpc':'2.0','method':'sms_server.reconnect_done','params':{'id': id, 'status': 'Ok'}}))

if __name__ == "__main__":
    app = App(URI)
    asyncio.get_event_loop().run_until_complete(app.listen())
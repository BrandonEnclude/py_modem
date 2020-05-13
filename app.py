import asyncio
import concurrent.futures
import websockets, ssl
from gsmmodem.exceptions import CmsError, CmeError
import pathlib
import json
import logging
from modem import SIMS
import time
import os
import sys

logging.basicConfig(filename='error.log', filemode='a', format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s', level=logging.ERROR)

URI = os.environ.get('WEBSOCKET_URI', 'ws://localhost:8000/ws/')
WS_KEY = os.environ.get('WS_KEY', 'ws_key')
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
        self.stay_connected = True

    async def listen(self):
        try:
            async with websockets.connect(self.URI, ssl = ssl_context, extra_headers=headers) as websocket:
                self.websocket = websocket
                await self.websocket.send(json.dumps({'id': int(time.time()), 'jsonrpc':'2.0','method':'sms_server.reconnect_done','params':{'status': 'Ok'}}))
                asyncio.create_task(self.poll_modem(self.websocket))
                while self.stay_connected:
                    msg = await self.websocket.recv()
                    asyncio.create_task(self._on_message(msg))
        except websockets.exceptions.ConnectionClosed:
            print('Websocked closed unexpectedly.', flush=True)
            await self._tear_down(3)
        except Exception as e:
            logging.error('at %s', 'App.listen', exc_info=e)
            await self._tear_down()

    async def poll_modem(self, ws):
        while ws.open and self.stay_connected:
            await asyncio.sleep(1)
            await ws.send(json.dumps({'id': int(time.time()), 'jsonrpc':'2.0','method':'sms_server.ping','params':{}}))
            # await self.sims.get_stored_messages()

    async def _on_message(self, msg):
        # Messages are passed according to the jsonrpc specification https://www.jsonrpc.org/specification
        jsonrpc = json.loads(msg)
        namespace, method_name, params = self._extract_params(jsonrpc)
        if method_name is not None and getattr(self, method_name) is not None:
            loop = asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor() as pool:

                method = getattr(self, method_name)
                
                result = await loop.run_in_executor(
                    pool,
                    await method(**params)
                )
                print('custom thread pool', flush=True)
                print(result, flush=True)
            

    async def _tear_down(self, delay = RECONNECT_DELAY):
        try:
            await self.sims.close_all()
            await self.websocket.close()
        except AttributeError as e:
            pass
        except Exception as e:
            logging.error('at %s', 'App._tear_down', exc_info=e)
        self.stay_connected = False

    def _extract_params(self, jsonrpc):
        if jsonrpc.get('result') is None and jsonrpc.get('method') is None:
            return None, None, None
        method_name = jsonrpc['result']['method'] if 'result' in jsonrpc.keys() else jsonrpc['method']
        namespace, method_name = method_name.split('.')
        params = jsonrpc['result']['params'] if 'result' in jsonrpc.keys() else jsonrpc['params']
        return namespace, method_name, params

    ### SIM Methods ###
    async def available_sims(self, sims):
        self.sims = SIMS(json.loads(sims), self.websocket)
        try:
            await self._connect_sims()
            await self.sim_status()
        except Exception as e:
            logging.error('at %s', 'App.available_sims', exc_info=e)

    async def _connect_sims(self):
        if self.sims:
            await self.sims.connect_all()

    async def sim_status(self, id = None):
        if self.sims:
            await self.websocket.send(json.dumps({'id': int(time.time()), 'jsonrpc':'2.0','method':'sms_server.broadcast_sim_status','params':{'sims': self.sims.to_dict()}}))

    def send_sms(self, msgId, msg, sim_number, recipient_number):
        if self.sims:

            try:
                self.sims.send_sms(msg, sim_number, recipient_number)
            except Exception as e:
                print(repr(e))
            # except (CmsError, CmeError) as e:
            #     await self.websocket.send(json.dumps({'id': int(time.time()), 'jsonrpc':'2.0','method':'sms_server.sent_status','params':{'msgId': msgId, 'message': f'ERR: {repr(e)}'}}))
            # except Exception as e:
            #     logging.error('at %s', 'App.send_sms', exc_info=e)
            #     await self.websocket.send(json.dumps({'id': int(time.time()), 'jsonrpc':'2.0','method':'sms_server.sent_status','params':{'msgId': msgId, 'message': f'ERR: {repr(e)}'}}))
            # else:
            #     await self.websocket.send(json.dumps({'id': int(time.time()), 'jsonrpc':'2.0','method':'sms_server.sent_status','params':{'msgId': msgId, 'message': 'Sent'}}))

    async def sent_sms_status(self, status):
        if self.sims:
            await self.websocket.send(json.dumps({'id': int(time.time()), 'jsonrpc':'2.0','method':'sms_server.sent_status','params':{'msgId': msgId, 'message': f'{status}'}}))

    async def delete_stored_sms(self, sim_number, msg_index):
        if self.sims:
            await self.sims.delete_stored_sms(sim_number, msg_index)

    async def reconnect(self):
        await self._tear_down(3)

if __name__ == "__main__":
    app = App(URI)
    asyncio.get_event_loop().run_until_complete(app.listen())

    
from types import MethodType
from gsmmodem.modem import GsmModem, StatusReport, Sms, ReceivedSms
from gsmmodem.pdu import decodeSmsPdu
from gsmmodem.exceptions import TimeoutException
from threading import Thread
from queue_task import DeleteSMSQueueTask, GetStoredSMSQueueTask, HandleIncomingSMSQueueTask, SendSMSQueueTask, PauseQueueTask
import time
import logging
import asyncio
import concurrent.futures
import json
import re
import serial

logging.basicConfig(filename='error.log', filemode='a', format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s', level=logging.ERROR)

class SIMS:
    def __init__(self, sims, socket):
        self.sims = {}
        self.socket = socket
        for sim in sims:
            number = sim['fields']['phone_number']
            port = sim['fields']['port_number']
            pin = sim['fields']['pin_number']
            self.sims[number] = SIM(number, port, pin, socket)

    async def connect_all(self):
        for key in self.sims.keys():
            await self.sims[key].connect()

    async def close_all(self):
        for key in self.sims.keys():
            await self.sims[key].close()

    async def get_stored_messages(self):
        for key in self.sims.keys():
            await self.sims[key].get_stored_messages()

    def to_dict(self):
        sims = {}
        for key in self.sims.keys():
            sims[key] = self.sims[key].to_dict()
        return sims

    async def send_sms(self, msgId, msg, sim_number, recipient_number, **kwargs):
        sim = self.get(sim_number)
        await sim.send_sms(msgId, recipient_number, msg)

    async def delete_stored_sms(self, sim_number, msg_index):
        sim = self.get(sim_number)
        await sim.delete_stored_sms(msg_index)

    def get(self, number):
        try:
            return self.sims[number]
        except KeyError:
            return None

    def remove(self, number):
        sim = self.sims.get(number)
        if sim is not None:
            sim.disconnect()
            del self.sims[number]

class SIM:
    def __init__(self, number, port, pin, socket):
        self.loop = asyncio.get_event_loop()
        self.listener = None
        self.number = number
        self.port = port
        self.pin = None if pin is None or pin == 'None' else int(pin)
        self.socket = socket

    def to_dict(self):
        return {'number': self.number, 'port': self.port, 'pin': self.pin, 'connected': self.connected, 'status': self.status, 'signal strength': self.signal_strength}

    async def delete_stored_sms(self, msgIndex):
        if self.listener:
            await self.listener.delete_stored_sms(msgIndex)

    async def close(self):
        if self.listener:
            await self.listener.close()

    @property
    def status(self):
        return self.listener.status if self.listener else None

    @property
    def signal_strength(self):
        return self.listener.signal_strength if self.listener else None

    async def connect(self):
        if self.listener:
            self.listener.modem.close()
            self.listener = None
        self.listener = SerialListener(self.number, self.port, self.pin, self.socket)
        
    async def get_stored_messages(self):
        if self.listener:
            await self.listener.get_stored_messages()

    async def disconnect(self):
        if self.listener is not None:
            asyncio.create_task(self.listener.close())
            del self.listener
            self.listener = None

    async def send_sms(self, msgId, number, msg):
        await self.listener.send_sms(msgId, number, msg)

    @property
    def connected(self):
        if self.listener is None:
            return False
        try:
            res = self.listener.modem.write('AT', parseError=False, timeout=1)
            return res is not None and 'OK' in res
        except Exception as e:
            logging.error('at %s', 'SIM.connected', exc_info=e)
            return False

class SerialListener(Thread):
    def __init__(self, number, port, pin, socket, BAUDRATE = 115200, smsTextMode = False):
        Thread.__init__(self)
        self.number = number
        self.port = port
        self.pin = pin
        self.socket = socket
        self.status = None
        self.BAUDRATE = BAUDRATE
        self.smsTextMode = smsTextMode
        self.queue = asyncio.PriorityQueue()
        logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.DEBUG)
        self.modem = Modem(self.port, self.BAUDRATE, smsReceivedCallbackFunc=self.handle_sms)
        try:
            self.modem.connect(pin=pin, waitingForModemToStartInSeconds=2) if self.pin else self.modem.connect(waitingForModemToStartInSeconds=2)
        except TimeoutException as e:
            self.status = 'Timeout Exception: Unable to connect to modem. Check that it is powered on and connected.'
        except Exception as e:
            logging.error('at %s', 'SerialListener.__init__', exc_info=e)
            self.status = repr(e)
        else:
            asyncio.create_task(self.queue_worker(self.queue))

    def run(self):
        try:
            self.modem.rxThread.join(2**31)
        except Exception as e:
            logging.error('at %s', 'SerialListener.run', exc_info=e)
        finally:
            self.modem.close()
    
    async def queue_worker(self, queue):
        loop = asyncio.get_event_loop()
        tasks_since_pause = 0
        while True:
            task = await queue.get()
            await asyncio.sleep(task.sleep)
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
                try:
                    await loop.run_in_executor(pool, task.run)
                except Exception as e:
                    logging.error('at %s', 'SerialListener.queue_worker', exc_info=e)
                for payload in task.payload_responses:
                    await self.socket.send(json.dumps(payload))
                for task in task.spawned_tasks:
                    self.queue.put_nowait(task)

            # if tasks_since_pause >= 5:
            #     tasks_since_pause = 0
            #     await self.queue_pause()

            # if queue.qsize() == 0 and isinstance(task, SendSMSQueueTask):
            #     await self.get_stored_messages()

            # elif isinstance(task, SendSMSQueueTask):
            #     tasks_since_pause += 1

            queue.task_done()

    async def pause_for_incoming(self):
        task_in_queue = False
        for item in self.queue._queue:
            if isinstance(item, PauseQueueTask):
                task_in_queue = True
                break
        if not task_in_queue:
            await self.queue_pause()

    async def send_sms(self, msgId, recipient, text):
        task = SendSMSQueueTask(self.modem, self.number, msgId, recipient, text)
        self.queue.put_nowait(task)

    async def delete_stored_sms(self, msg_index):
        task = DeleteSMSQueueTask(self.modem, self.number, msg_index, priority=2)
        self.queue.put_nowait(task)

    async def close(self):
        return await asyncio.coroutine(self.modem.close)()

    async def get_stored_messages(self):
        task = GetStoredSMSQueueTask(self.modem, self.number, priority=1)
        self.queue.put_nowait(task)

    def handle_sms(self, sms):
        task = HandleIncomingSMSQueueTask(self.modem, self.number, sms, priority=3)
        self.queue.put_nowait(task)

    async def queue_pause(self):
        task = PauseQueueTask(self.modem, self.number, priority=0)
        self.queue.put_nowait(task)

    @property
    def signal_strength(self):
        try:
            return self.modem.signalStrength
        except Exception as e:
            logging.error('at %s', 'SerialListener.signal_strength', exc_info=e)
            return -1

class Modem(GsmModem):
    def __init__(self, port, BAUDRATE, smsReceivedCallbackFunc):
        GsmModem.__init__(self, port, BAUDRATE, smsReceivedCallbackFunc=smsReceivedCallbackFunc, AT_CNMI='3,1,0,2,0') #AT_CNMI='3,1,0,0' ?

    # Overrides method due to modem peculiarities
    def deleteStoredSms(self, index, memory=None):
        self.write('AT+CMGD={0}'.format(index))

    def _handleSmsReceived(self, notificationLine):
        if self.smsReceivedCallback is not None:
            cmtiMatch = self.CMTI_REGEX.match(notificationLine)
            if cmtiMatch:
                msgMemory = cmtiMatch.group(1)
                msgIndex = cmtiMatch.group(2)
                sms = self.readStoredSms(msgIndex, msgMemory)
                sms.msgIndex = msgIndex
                try:
                    self.smsReceivedCallback(sms)
                except Exception as e:
                    logging.error('at %s', 'Modem._handleSmsReceived', exc_info=e)
                    
    # Revised method to include memory index on the Sms object for future deletion
    def listStoredSmsWithIndex(self, status=Sms.STATUS_ALL, memory='MT'):
        self._setSmsMemory(readDelete=memory)
        messages = []
        cmglRegex = re.compile(r'^\+CMGL:\s*(\d+),\s*(\d+),.*$')
        readPdu = False
        result = self.write('AT+CMGL={0}'.format(status))
        for line in result:
            if not readPdu:
                cmglMatch = cmglRegex.match(line)
                if cmglMatch:
                    msgIndex = int(cmglMatch.group(1))
                    msgStat = int(cmglMatch.group(2))
                    readPdu = True
            else:
                try:
                    smsDict = decodeSmsPdu(line)
                except Exception as e:
                    logging.error(' at %s', 'Modem.listStoredSmsWithIndex', exc_info=e)
                    pass
                else:
                    if smsDict['type'] == 'SMS-DELIVER':
                        sms = ReceivedSms(self, int(msgStat), smsDict['number'], smsDict['time'], smsDict['text'], smsDict['smsc'], smsDict.get('udh', []))
                    elif smsDict['type'] == 'SMS-STATUS-REPORT':
                        sms = StatusReport(self, int(msgStat), smsDict['reference'], smsDict['number'], smsDict['time'], smsDict['discharge'], smsDict['status'])
                    sms.msgIndex = msgIndex
                    messages.append(sms)
                    readPdu = False
        return messages

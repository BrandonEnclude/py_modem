from types import MethodType
from gsmmodem.modem import GsmModem, StatusReport, Sms, ReceivedSms
from gsmmodem.pdu import decodeSmsPdu
from gsmmodem.exceptions import TimeoutException
from threading import Thread
import logging
import asyncio
import json
import re
import serial
import emoji

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

    async def send_sms(self, msg, sim_number, recipient_number, **kwargs):
        sim = self.get(sim_number)
        await sim.send_sms(recipient_number, msg)

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
        self.listener = SerialListener(self.number, self.port, self.pin, self.handle_sms)
    async def get_stored_messages(self):
        storedMessages = await self.listener.list_stored_sms_with_index()
        if storedMessages is not None:
            for sms in storedMessages:
                if type(sms) is StatusReport:
                    # self.listener.modem.deleteStoredSms(sms.msgIndex, memory='MT')
                    asyncio.create_task(asyncio.coroutine(self.listener.modem.deleteStoredSms)(sms.msgIndex, memory='MT')) 
                else:
                    try:
                        self.handle_sms(sms)
                    except Exception as e:
                        logging.error('at %s', 'SIM.get_stored_messages', exc_info=e)

    async def disconnect(self):
        if self.listener is not None:
            asyncio.create_task(self.listener.close())
            del self.listener
            self.listener = None

    def handle_sms(self, sms):
        data = {'msg_index': sms.msgIndex ,'time': sms.time.isoformat(), 'recipient': self.number, 'sender': sms.number, 'message': sms.text }
        res = {"id":sms.msgIndex, "jsonrpc":"2.0","method":"sms_server.on_received","params":{"data": data}}
        asyncio.create_task(self.socket.send(json.dumps(res))

    async def send_sms(self, number, msg):
        await self.listener.send_sms(number, emoji.demojize(msg))

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
    def __init__(self, number, port, pin, callback, BAUDRATE = 115200, smsTextMode = False):
        Thread.__init__(self)
        self.number = number
        self.port = port
        self.pin = pin
        self.callback = callback
        self.status = None
        self.BAUDRATE = BAUDRATE
        self.smsTextMode = smsTextMode
        logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.DEBUG)
        self.modem = Modem(self.port, self.BAUDRATE, smsReceivedCallbackFunc=self.callback)
        try:
            self.modem.connect(pin=pin, waitingForModemToStartInSeconds=2) if self.pin else self.modem.connect(waitingForModemToStartInSeconds=2)
        except TimeoutException as e:
            self.status = 'Timeout Exception: Unable to connect to modem. Check that it is powered on and connected.'
        except Exception as e:
            logging.error('at %s', 'SerialListener.__init__', exc_info=e)
            self.status = repr(e)

    def run(self):
        try:
            self.modem.rxThread.join(2**31)
        except Exception as e:
            logging.error('at %s', 'SerialListener.run', exc_info=e)
        finally:
            self.modem.close()

    async def send_sms(self, recipient, text):
        return await asyncio.coroutine(self.modem.sendSms)(recipient, text)

    async def delete_stored_sms(self, msg_index):
        return await asyncio.coroutine(self.modem.deleteStoredSms)(msg_index)

    async def close(self):
        asyncio.get_event_loop().run_in_executor(None, self.modem.close())

    async def list_stored_sms_with_index(self):
        try:
            return await asyncio.coroutine(self.modem.listStoredSmsWithIndex)(memory='MT')
        except Exception as e:
            logging.error('at %s', 'SerialListener.list_stored_sms_with_index', exc_info=e)

    @property
    def signal_strength(self):
        try:
            return self.modem.signalStrength
        except Exception as e:
            logging.error('at %s', 'SerialListener.signal_strength', exc_info=e)
            return -1

class Modem(GsmModem):
    def __init__(self, port, BAUDRATE, smsReceivedCallbackFunc):
        GsmModem.__init__(self, port, BAUDRATE, smsReceivedCallbackFunc=smsReceivedCallbackFunc)

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
    def listStoredSmsWithIndex(self, status=Sms.STATUS_ALL, memory=None):
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

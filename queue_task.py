import emoji
import time
from gsmmodem.modem import StatusReport, TimeoutException, CmeError, CmsError
class QueueTask:
    def __init__(self, modem, number, priority = 10):
        self.modem = modem
        self.number = number
        self.payload_responses = []
        self.spawned_tasks = []
        self.priority = priority

    def __lt__(self, other):
        return self.priority < other.priority

    def __gt__(self, other):
        return self.priority > other.priority

    def __eq__(self, other):
        return self.priority == other.priority

class DeleteSMSQueueTask(QueueTask):
    def __init__(self, modem, number, index, **kwargs):
        QueueTask.__init__(self, modem, number, **kwargs)
        self.index = index

    def run(self):
        self.modem.deleteStoredSms(self.index)

class GetStoredSMSQueueTask(QueueTask):
    def __init__(self, modem, number, memory='MT', **kwargs):
        self.memory=memory
        self.delete_indexes = []
        QueueTask.__init__(self, modem, number, **kwargs)

    def run(self):
        busy = self.modem.gsmBusy
        print(busy, flush=True)
        stored_messages = None
        try:
            stored_messages = self.modem.listStoredSmsWithIndex(memory=self.memory)
        except (TimeoutException, CmeError, CmsError):
            try:
                stored_messages = self.modem.listStoredSmsWithIndex(memory=self.memory)
            except (TimeoutException, CmeError, CmsError):
                pass
        if stored_messages is not None:
            for sms in stored_messages:
                if type(sms) is StatusReport:
                    self.spawned_tasks.append(DeleteSMSQueueTask(self.modem, self.number, sms.msgIndex, priority=1))
                else:
                    data = {'msg_index': sms.msgIndex ,'time': sms.time.isoformat(), 'recipient': self.number, 'sender': sms.number, 'message': sms.text }
                    payload = {"id":sms.msgIndex, "jsonrpc":"2.0","method":"sms_server.on_received","params":{"data": data}}
                    self.payload_responses.append(payload)

class HandleIncomingSMSQueueTask(QueueTask):
    def __init__(self, modem, number, sms, **kwargs):
        self.sms = sms
        QueueTask.__init__(self, modem, number, **kwargs)

    def run(self):
        if type(self.sms) is StatusReport:
            self.spawned_tasks.append(DeleteSMSQueueTask(self.modem, self.number, sms.msgIndex, priority=1))
        else:
            data = {'msg_index': self.sms.msgIndex ,'time': self.sms.time.isoformat(), 'recipient': self.number, 'sender': self.sms.number, 'message': emoji.demojize(self.sms.text) }
            payload = {"id":self.sms.msgIndex, "jsonrpc":"2.0","method":"sms_server.on_received","params":{"data": data}}
            self.payload_responses.append(payload)

class SendSMSQueueTask(QueueTask):
    def __init__(self, modem, number, msgId, recipient, text, **kwargs):
        QueueTask.__init__(self, modem, number, **kwargs)
        self.msgId = msgId
        self.recipient = recipient
        self.text = emoji.demojize(text)

    def run(self):
        try:
            self.modem.sendSms(self.recipient, self.text)
        except Exception as e:
            payload_response = {'id': int(time.time()), 'jsonrpc':'2.0','method':'sms_server.sent_status','params':{'msgId': self.msgId, 'message': f'{repr(e)}'}}
            self.payload_responses.append(payload_response)
        else:
            status = 'Delivered'
            payload_response = {'id': int(time.time()), 'jsonrpc':'2.0','method':'sms_server.sent_status','params':{'msgId': self.msgId, 'message': f'{status}'}}
            self.payload_responses.append(payload_response)
import mock
import unittest
import gcm
import datetime
import urlparse
import base64
import pickle

from google.appengine.api.urlfetch_stub import URLFetchServiceStub
from google.appengine.ext import testbed


def get_mock_retrieve_url(status_code=200, content='{"results": [], "failure": 0, "canonical_ids": []}', headers={}):
    override_headers = headers
    def _mock_retrieve_url(url, payload, method, headers, request, response, *args, **kwargs):
        response.set_content(content)
        response.set_statuscode(status_code)

        if override_headers:
            for k,v in override_headers.items():
                header_proto = response.add_header()
                header_proto.set_key(k)
                header_proto.set_value(v)

    return _mock_retrieve_url


class GCMMessageTests(unittest.TestCase):
    def setUp(self):
        self.testbed = testbed.Testbed()

        self.testbed.activate()

        self.testbed.init_urlfetch_stub()
        self.testbed.init_taskqueue_stub(root_path='.')
        self.taskqueue_stub = self.testbed.get_stub(testbed.TASKQUEUE_SERVICE_NAME)

    def test_message_construction(self):
        message = gcm.GCMMessage('api_key', ['testtoken'], {'message': 'wake up!'})

        self.assertEqual(message.json_string(),
            """{"data": {"message": "wake up!"}, "registration_ids": ["testtoken"]}"""
        )

    @mock.patch.object(URLFetchServiceStub, "_RetrieveURL", wraps=get_mock_retrieve_url())
    def test_message_send(self, _RetrieveURL):
        message = gcm.GCMMessage('api_key', ['testtoken'], {'message': 'wake up!'})
        response = message.send_message()

        self.assertEqual(200, response.status_code)

    @mock.patch.object(URLFetchServiceStub, "_RetrieveURL", wraps=get_mock_retrieve_url(status_code=503, headers={"Retry-After": 30}))
    def test_message_throttled_honour_retry_after(self, _RetrieveURL):
        message = gcm.GCMMessage('api_key', ['testtoken'], {'message': 'wake up!'})
        response = message.send_message()

        self.assertEqual(503, response.status_code)

        tasks = self.taskqueue_stub.GetTasks(gcm.GCM_QUEUE_NAME)
        self.assertEqual(1, len(tasks))

        eta = datetime.datetime.strptime(tasks[0]['eta'], '%Y/%m/%d %H:%M:%S')
        delta = eta - datetime.datetime.utcnow()

        self.assertTrue(30 > delta.total_seconds() > 29) # shouldn't take more than a second to get here...

    @mock.patch.object(URLFetchServiceStub, "_RetrieveURL", wraps=get_mock_retrieve_url(status_code=401))
    def test_message_retry_exp_backoff(self, _RetrieveURL):
        message = gcm.GCMMessage('api_key', ['testtoken'], {'message': 'wake up!'})
        response = message.send_message()

        self.assertEqual(401, response.status_code)

        for countdown in (2**i*10 for i in range(0,10)): # simulate retrying a few times
            tasks = self.taskqueue_stub.GetTasks(gcm.GCM_QUEUE_NAME)
            self.assertEqual(1, len(tasks))

            eta = datetime.datetime.strptime(tasks[0]['eta'], '%Y/%m/%d %H:%M:%S')
            delta = eta - datetime.datetime.utcnow()

            self.assertTrue(countdown > delta.total_seconds() > countdown-1)

            invoke_member, args, kwargs = pickle.loads(base64.b64decode(tasks[0]['body']))
            invoke_member(*args, **kwargs)
            self.taskqueue_stub.DeleteTask(gcm.GCM_QUEUE_NAME, tasks[0]['name'])

    @mock.patch.object(URLFetchServiceStub, "_RetrieveURL", 
        wraps=get_mock_retrieve_url(content='{"results": [{"message_id": "msg1", "registration_id": "new_token"}], "failure": 0, "canonical_ids": []}'))
    def test_update_device_token(self, _RetrieveURL):
        update_token_mock = mock.MagicMock()
        gcm.GCMMessage('api_key', ['testtoken'], {'message': 'wake up!'}, update_token=update_token_mock).send_message()

        update_token_mock.assert_called_once_with("testtoken", "new_token")


    @mock.patch.object(URLFetchServiceStub, "_RetrieveURL", 
        wraps=get_mock_retrieve_url(content='{"results": [{"message_id": "msg1", "registration_id": "new_token"}], "failure": 0, "canonical_ids": []}'))
    def test_update_device_token(self, _RetrieveURL):
        update_token_mock = mock.MagicMock()
        gcm.GCMMessage('api_key', ['testtoken'], {'message': 'wake up!'}, update_token=update_token_mock).send_message()

        update_token_mock.assert_called_once_with("testtoken", "new_token")

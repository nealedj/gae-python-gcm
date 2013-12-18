import mock
import unittest
import gcm
import datetime
import urlparse
import base64
import pickle

from google.appengine.api.urlfetch_stub import URLFetchServiceStub
from google.appengine.ext import testbed


def get_mock_retrieve_url(status_code=200, content='{"results": [], "failure": 0, "canonical_ids": 0}', headers={}):
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

def update_token_mock(old_token, new_token, user_id=None):
    update_token_mock.user_id = user_id
    update_token_mock.old_token = old_token
    update_token_mock.new_token = new_token

def delete_token_mock(token, user_id=None):
    delete_token_mock.user_id = user_id
    delete_token_mock.token = token

def reset_module_mocks():
    update_token_mock.old_token = update_token_mock.new_token = update_token_mock.user_id = delete_token_mock.token = delete_token_mock.user_id = None

class GCMMessageTests(unittest.TestCase):
    def setUp(self):
        self.testbed = testbed.Testbed()

        self.testbed.activate()

        self.testbed.init_urlfetch_stub()
        self.testbed.init_taskqueue_stub(root_path='.')
        self.taskqueue_stub = self.testbed.get_stub(testbed.TASKQUEUE_SERVICE_NAME)

    def tearDown(self):
        reset_module_mocks()

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
        wraps=get_mock_retrieve_url(content='{"results": [{"message_id": "msg1", "registration_id": "new_token"}], "failure": 0, "canonical_ids": 1}'))
    def test_update_device_token(self, _RetrieveURL):
        gcm.GCMMessage('api_key', ['testtoken'], {'message': 'wake up!'}, update_token=update_token_mock, callback_kwargs={'user_id': 42}).send_message()

        self.assertEqual(getattr(update_token_mock, "user_id", False), 42)
        self.assertEqual(getattr(update_token_mock, "old_token", False), "testtoken")
        self.assertEqual(getattr(update_token_mock, "new_token", None), "new_token")

    def test_delete_bad_device_token(self):
        response_template = '{{"results": [{{"error": "{0}"}}], "failure": 1, "canonical_ids": 0}}'

        for error_msg in ['InvalidRegistration', 'MismatchSenderId', 'NotRegistered']:
            with mock.patch.object(URLFetchServiceStub, "_RetrieveURL",
                wraps=get_mock_retrieve_url(content=response_template.format(error_msg))):

                gcm.GCMMessage('api_key', ['testtoken'], {'message': 'wake up!'}, delete_bad_token=delete_token_mock, callback_kwargs={'user_id': 42}).send_message()

                self.assertEqual(getattr(delete_token_mock, "user_id", False), 42)
                self.assertEqual(getattr(delete_token_mock, "token", False), "testtoken")

    def test_deferral_with_callback_functions(self):
        """ This tests that passing a callback function in the update_device_token or delete_bad_device_token arguments doesn't cause any 
        issues when the message gets serialised to a deferred task """
        with mock.patch.object(URLFetchServiceStub, "_RetrieveURL", wraps=get_mock_retrieve_url(status_code=503, headers={"Retry-After": 30})):
            # this should fail and cause a deferred task to be created for retry
            gcm.GCMMessage('api_key', ['testtoken'], {'message': 'wake up!'}, update_token=update_token_mock, callback_kwargs={'user_id': 42}).send_message()

        tasks = self.taskqueue_stub.GetTasks(gcm.GCM_QUEUE_NAME)
        self.assertEqual(1, len(tasks))

        invoke_member, args, kwargs = pickle.loads(base64.b64decode(tasks[0]['body']))

        with mock.patch.object(URLFetchServiceStub, "_RetrieveURL",
            wraps=get_mock_retrieve_url(content='{"results": [{"message_id": "msg1", "registration_id": "new_token"}], "failure": 0, "canonical_ids": 1}')):
            invoke_member(*args, **kwargs)

        self.assertEqual(getattr(update_token_mock, "user_id", False), 42)
        self.assertEqual(getattr(update_token_mock, "old_token", False), "testtoken")
        self.assertEqual(getattr(update_token_mock, "new_token", None), "new_token")

    def test_message_throws_if_unpicklable(self):
        self.assertRaises(pickle.PicklingError, gcm.GCMMessage, 'api_key', ['testtoken'], {}, update_token=lambda: None, delete_bad_token=lambda: None)

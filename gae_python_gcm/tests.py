import mock
import unittest
import gcm

from google.appengine.api.urlfetch_stub import URLFetchServiceStub
from google.appengine.ext import testbed


def get_mock_retrieve_url(status_code=200, content='{"results": [], "failure": 0, "canonical_ids": []}'):
    def _mock_retrieve_url(url, payload, method, headers, request, response, *args, **kwargs):
        response.set_content(content)
        response.set_statuscode(status_code)
    return _mock_retrieve_url


class GCMMessageTests(unittest.TestCase):
    def setUp(self):
        self.testbed = testbed.Testbed()

        self.testbed.activate()

        self.testbed.init_urlfetch_stub()

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

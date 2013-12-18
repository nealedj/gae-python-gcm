################################################################################
# gae_python_gcm/gcm.py
# 
# In Python, for Google App Engine
# Originally ported from https://github.com/Instagram/node2dm
# Extended to support new GCM API.
# Greg Bayer <greg@gbayer.com>
# 
# Further extended by David Neale (neale.dj@gmail.com)
################################################################################

import logging
import pickle
try:
    import json
except ImportError:
    import simplejson as json

from google.appengine.api import urlfetch
from google.appengine.ext import deferred

import gcm_exceptions

DEBUG = False

try: 
    from settings import DEBUG
except:
    pass

GOOGLE_LOGIN_URL = 'https://www.google.com/accounts/ClientLogin'
# Can't use https on localhost due to Google cert bug
GOOGLE_GCM_SEND_URL = 'http://android.apis.google.com/gcm/send' if DEBUG \
else 'https://android.apis.google.com/gcm/send'
GOOGLE_GCM_SEND_URL = 'http://android.googleapis.com/gcm/send' if DEBUG \
else 'https://android.googleapis.com/gcm/send'

GCM_QUEUE_NAME = 'gcm-retries'


class GCMMessage:

    def __init__(self, gcm_api_key, device_tokens, notification, collapse_key=None, delay_while_idle=None, time_to_live=None, update_token=None, delete_bad_token=None):
        if isinstance(device_tokens, list):
            self.device_tokens = device_tokens
        else:
            self.device_tokens = [device_tokens]

        self.gcm_api_key = gcm_api_key
        self.notification = notification
        self.collapse_key = collapse_key
        self.delay_while_idle = delay_while_idle
        self.time_to_live = time_to_live
        self.update_token = update_token
        self.delete_bad_token = delete_bad_token
        self.retries = 0

        self.verify_is_pickleable()

    def verify_is_pickleable(self):
        """Try to serialise the object"""
        pickle.dumps(self, protocol=pickle.HIGHEST_PROTOCOL)

    def json_string(self):
        assert self.device_tokens and isinstance(self.device_tokens, list), "GCMMessage.json_string error. Invalid device tokens"

        json_dict = {} 
        json_dict['registration_ids'] = self.device_tokens
 
        # If message is a dict, send each key individually
        # Else, send entire message under data key
        if isinstance(self.notification, dict):
            json_dict['data'] = self.notification
        else:
            json_dict['data'] = {'data': self.notification}

        if self.collapse_key:
            json_dict['collapse_key'] = self.collapse_key
        if self.delay_while_idle:
            json_dict['delay_while_idle'] = self.delay_while_idle
        if self.time_to_live:
            json_dict['time_to_live'] = self.time_to_live 

        json_str = json.dumps(json_dict)
        return json_str

    @property
    def is_deferred(self):
        # dirty way to work out if this message is executing within a deferred task
        return bool(self.retries)

    def _process_successful_response(self, resp):
        resp_json = json.loads(resp.content)
        logging.info('_process_successful_response() resp_json: ' + repr(resp_json))

        if resp_json.get('failure') or resp_json.get('canonical_ids'):
            # Process result messages for each token (result index matches original token index from message) 
            for result_index, result in enumerate(resp_json.get('results', [])):

                if 'message_id' in result and 'registration_id' in result:
                    # Update device token
                    try:
                        if self.update_token:
                            self.update_token(self.device_tokens[result_index], result['registration_id'])
                    except:
                        logging.exception('Error updating device token')
                    return

                elif 'error' in result:
                    # Handle GCM error
                    error_msg = result.get('error')
                    try:
                        device_token = self.device_tokens[result_index]
                        self._message_error(device_token, error_msg)
                    except:
                        logging.exception('Error handling GCM error: ' + repr(error_msg))
                    return

                result_index += 1

    def process_message_response(self, rpc, gcm_post_json_str):
        resp = rpc.get_result()

        if resp.status_code == 200:
            self._process_successful_response(resp)
        elif resp.status_code == 400:
            raise gcm_exceptions.BadRequestException(gcm_post_json_str)
        elif resp.status_code == 401:
            logging.error('401, Error authenticating with GCM. Retrying message. Might need to fix auth key! This is retry {0}'.format(self.retries))
            deferred.defer(self.send_message, retry=True, _queue=GCM_QUEUE_NAME, _countdown=2**self.retries*10)
        elif resp.status_code == 503:
            retry_seconds = int(resp.headers.get('Retry-After', 10))
            logging.error('503, Throttled. Retry after delay. Requeuing message. Delay in seconds: {0}. This is retry {1}'.format(retry_seconds, self.retries+1))
            deferred.defer(self.send_message, retry=True, _queue=GCM_QUEUE_NAME, _countdown=2**self.retries*retry_seconds)
        elif 500 <= resp.status_code < 600:
            raise gcm_exceptions.InternalServerErrorException('{0}, Internal error in the GCM server while trying to send message: {1}'.format(resp.status_code, repr(gcm_post_json_str)))


    # Try sending message now
    def send_message_async(self):
        assert self.device_tokens and self.notification, 'Message must contain device_tokens and notification.'

        rpc = urlfetch.create_rpc()

        gcm_post_json_str = self.json_string()

        logging.info('Sending gcm_post_body: ' + repr(gcm_post_json_str))

        headers = {
            'Authorization': 'key=' + self.gcm_api_key,
            'Content-Type': 'application/json'
        }

        rpc.callback = lambda: self.process_message_response(rpc, gcm_post_json_str)
        urlfetch.make_fetch_call(rpc, GOOGLE_GCM_SEND_URL, payload=gcm_post_json_str, headers=headers, method=urlfetch.POST)

        return rpc

    def send_message(self, retry=False):
        if retry:
            self.retries += 1
        try:
            return self.send_message_async().get_result()
        except Exception, e:
            if self.is_deferred:
                logging.exception(e)
            else:
                raise

    def _delete_bad_token(self, device_token):
        if self.delete_bad_token:
            logging.error('Deleting token {0}'.format(repr(device_token)))
            self.delete_bad_token(device_token)

    def _message_error(self, device_token, error_msg):

        if error_msg == "MissingRegistration":
            raise gcm_exceptions.MissingRegistrationException

        elif error_msg == "InvalidRegistration":
            logging.error('ERROR: Device token is invalid: {0}'.format(repr(device_token)))
            self._delete_bad_token(device_token)

        elif error_msg == "MismatchSenderId":
            logging.error('ERROR: Device token is tied to a different sender id: {0}'.format(repr(device_token)))
            self._delete_bad_token(device_token)

        elif error_msg == "NotRegistered":
            logging.error('ERROR: Device token not registered: {0}'.format(repr(device_token)))
            self._delete_bad_token(device_token)

        elif error_msg == "MessageTooBig":
            raise gcm_exceptions.MessageTooBigException

        elif error_msg == "InvalidTtl":
            raise gcm_exceptions.InvalidTtlException

        elif error_msg == "InvalidDataKey":
            raise gcm_exceptions.InvalidDataKeyException

        elif error_msg == "Unavailable":
            retry_seconds = 10
            logging.error('ERROR: GCM Unavailable. Retry after delay. Requeuing message. Delay in seconds: {0}. This is retry {1}'.format(retry_seconds, self.retries+1))
            deferred.defer(self.send_message, retry=True, _queue=GCM_QUEUE_NAME, _countdown=2**self.retries*retry_seconds)
        
        elif error_msg == "InternalServerError":
            raise gcm_exceptions.InternalServerErrorException("ERROR: Internal error in the GCM server while trying to send message: " + repr(self))

        else:
            raise gcm_exceptions.GCMException("Unknown error: %s for device token: %s" % (repr(error_msg), repr(device_token)))




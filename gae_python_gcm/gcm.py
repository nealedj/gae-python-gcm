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

from datetime import datetime, timedelta
import logging

try:
    import json
except ImportError:
    import simplejson as json

from google.appengine.api import urlfetch, taskqueue
from google.appengine.ext import deferred

DEBUG = False

try: 
    from settings import DEBUG
except:
    logging.info('GCM settings module not found. Using defaults.')
    pass

GOOGLE_LOGIN_URL = 'https://www.google.com/accounts/ClientLogin'
# Can't use https on localhost due to Google cert bug
GOOGLE_GCM_SEND_URL = 'http://android.apis.google.com/gcm/send' if DEBUG \
else 'https://android.apis.google.com/gcm/send'
GOOGLE_GCM_SEND_URL = 'http://android.googleapis.com/gcm/send' if DEBUG \
else 'https://android.googleapis.com/gcm/send'

GCM_QUEUE_NAME = 'gcm-retries'


class GCMMessage:

    def __init__(self, gcm_api_key, device_tokens, notification, collapse_key=None, delay_while_idle=None, time_to_live=None, update_token=None):
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
        self.retries = 0

    def __unicode__(self):
        return "%s:%s:%s:%s:%s" % (repr(self.device_tokens), repr(self.notification), repr(self.collapse_key), repr(self.delay_while_idle), repr(self.time_to_live))

    def json_string(self):

        if not self.device_tokens or not isinstance(self.device_tokens, list):
            logging.error('GCMMessage generate_json_string error. Invalid device tokens: ' + repr(self))
            raise Exception('GCMMessage generate_json_string error. Invalid device tokens.')

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


    ##### Hooks - Override to change functionality #####

    def delete_bad_token(self, bad_device_token):
        logging.info('delete_bad_token(): ' + repr(bad_device_token))

    # Currently unused
    def login_complete(self):
        # Retries are handled by the gae task queue
        # self.retry_pending_messages()
        pass


    def _process_successful_response(self, resp):
        resp_json_str = resp.content
        resp_json = json.loads(resp_json_str)
        logging.info('_send_request() resp_json: ' + repr(resp_json))

        failure = resp_json['failure']
        canonical_ids = resp_json['canonical_ids']
        results = resp_json['results']

        # If the value of failure and canonical_ids is 0, it's not necessary to parse the remainder of the response.
        if failure == 0 and canonical_ids == 0:
            # Success, nothing to do
            return
        else:
            # Process result messages for each token (result index matches original token index from message) 
            result_index = 0
            for result in results:

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
                        # TODO: do this via a callback
                        pass
                        # device_token = message.device_tokens[result_index]
                        # self._on_error(device_token, error_msg, message)
                    except:
                        logging.exception('Error handling GCM error: ' + repr(error_msg))
                    return

                result_index += 1

    def process_message_response(self, rpc, gcm_post_json_str):
        # Post
        try:
            resp = rpc.get_result()

            if resp.status_code == 200:
                self._process_successful_response(resp)
            elif resp.status_code == 400:
                logging.error('400, Invalid GCM JSON message: ' + repr(gcm_post_json_str))
            elif resp.status_code == 401:
                logging.error('401, Error authenticating with GCM. Retrying message. Might need to fix auth key! This is retry {0}'.format(self.retries))
                try:
                    deferred.defer(self.send_message, retry=True, _queue=GCM_QUEUE_NAME, _countdown=2**self.retries*10)
                except taskqueue.UnknownQueueError:
                    logging.error("ERROR: could not defer task as queue %s doesn't exist" % GCM_QUEUE_NAME)
            elif resp.status_code == 500:
                logging.error('500, Internal error in the GCM server while trying to send message: ' + repr(gcm_post_json_str))
            elif resp.status_code == 503:
                retry_seconds = int(resp.headers.get('Retry-After', 10))
                logging.error('503, Throttled. Retry after delay. Requeuing message. Delay in seconds: {0}. This is retry {1}'.format(retry_seconds, self.retries+1))
                try:
                    deferred.defer(self.send_message, retry=True, _queue=GCM_QUEUE_NAME, _countdown=2**self.retries*retry_seconds)
                except taskqueue.UnknownQueueError:
                    logging.error("ERROR: could not defer task as queue %s doesn't exist" % GCM_QUEUE_NAME)

        except urlfetch.Error, e:
            logging.exception('Unexpected urlfetch Error: ' + repr(e))


    # Try sending message now
    def send_message_async(self):
        if self.device_tokens == None or self.notification == None:
            logging.error('Message must contain device_tokens and notification.')
            return False

        # Build request
        headers = {
                   'Authorization': 'key=' + self.gcm_api_key,
                   'Content-Type': 'application/json'
                   }

        gcm_post_json_str = ''
        try:
            gcm_post_json_str = self.json_string()
        except:
            logging.exception('Error generating json string for message: ' + repr(self))
            return

        logging.info('Sending gcm_post_body: ' + repr(gcm_post_json_str))

        rpc = urlfetch.create_rpc()
        rpc.callback = lambda: self.process_message_response(rpc, gcm_post_json_str)
        urlfetch.make_fetch_call(rpc, GOOGLE_GCM_SEND_URL, payload=gcm_post_json_str, headers=headers, method=urlfetch.POST)

        return rpc

    def send_message(self, retry=False):
        if retry:
            self.retries += 1
        return self.send_message_async().get_result()

    def _on_error(self, device_token, error_msg):

        if error_msg == "MissingRegistration":
            logging.error('ERROR: GCM message sent without device token. This should not happen!')

        elif error_msg == "InvalidRegistration":
            self.delete_bad_token(device_token)

        elif error_msg == "MismatchSenderId":
            logging.error('ERROR: Device token is tied to a different sender id: ' + repr(device_token))
            self.delete_bad_token(device_token)

        elif error_msg == "NotRegistered":
            self.delete_bad_token(device_token)

        elif error_msg == "MessageTooBig":
            logging.error("ERROR: GCM message too big (max 4096 bytes).")

        elif error_msg == "InvalidTtl":
            logging.error("ERROR: GCM Time to Live field must be an integer representing a duration in seconds between 0 and 2,419,200 (4 weeks).")

        elif error_msg == "MessageTooBig":
            logging.error("ERROR: GCM message too big (max 4096 bytes).")

        elif error_msg == "Unavailable":
            retry_seconds = 10
            logging.error('ERROR: GCM Unavailable. Retry after delay. Requeuing message. Delay in seconds: {0}. This is retry {1}'.format(retry_seconds, self.retries+1))
            try:
                deferred.defer(self.send_message, retry=True, _queue=GCM_QUEUE_NAME, _countdown=2**self.retries*retry_seconds)
            except taskqueue.UnknownQueueError:
                logging.error("ERROR: could not defer task as queue %s doesn't exist" % GCM_QUEUE_NAME)
        
        elif error_msg == "InternalServerError":
            logging.error("ERROR: Internal error in the GCM server while trying to send message: " + repr(self))

        else:
            logging.error("Unknown error: %s for device token: %s" % (repr(error_msg), repr(device_token)))




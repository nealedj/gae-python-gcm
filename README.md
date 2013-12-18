# About

gae-python-gcm is a simple implementation of [Google Cloud Messaging](http://developer.android.com/google/gcm/index.html) for [Google App Engine](https://developers.google.com/appengine/docs/python/overview) in Python.

This module is designed to take care of everything you have to think about when working with Android GCM messages on the server:

* Takes advantage of App Engine's task queues to make retries asynchronous
* Takes advantage of async API exposes by App Engine
* Provides two hook functions, **delete_bad_token** and **update_token**, which can be used handle token-related errors from GCM 

# Examples

```python
from gae_python_gcm.gcm import GCMMessage

GCM_API_KEY = 'YOUR_API_KEY'

push_token = 'GCM_REGISTRATION_ID'
notification_payload = {'your-key': 'your-value'}

gcm_message = GCMMessage(GCM_API_KEY, push_token, notification_payload)
gcm_message.send_message()
```

## With hook functions

```python
import logging
from gae_python_gcm.gcm import GCMMessage

GCM_API_KEY = 'YOUR_API_KEY'

def update_token(old_token, new_token, user_id=None):
	# here you might update your saved token for this user
	logging.warn("User {0} has a new token: {1}".format(user_id, new_token))

def delete_bad_token(token, user_id=None):
	# here you might delete your saved token for this user
	logging.warn("User {0} has an invalid token".format(user_id))

push_token = 'GCM_REGISTRATION_ID'
notification_payload = {'your-key': 'your-value'}

gcm_message = GCMMessage(GCM_API_KEY, push_token, notification_payload, update_token=update_token, delete_bad_token=delete_bad_token)
gcm_message.send_message()
```

## Async example
```python
from gae_python_gcm.gcm import GCMMessage

GCM_API_KEY = 'YOUR_API_KEY'

push_tokens = ['TOKEN_1', 'TOKEN_2', 'TOKEN_3', 'TOKEN_4']
notification_payload = {'your-key': 'your-value'}

rpcs = []
for token in push_tokens:
	gcm_message = GCMMessage(GCM_API_KEY, push_token, notification_payload)
	rpcs.append(gcm_message.send_message_async())

for rpc in rpcs:
    rpc.check_success()
```


# Getting started

To add gae-python-gcm to your AppEngine project:

1. git clone git://github.com/nealedj/gae-python-gcm.git
2. Add queue to your queue.yaml based on queue.yaml.
3. Copy the gae-python-gcm directory into your appengine project.



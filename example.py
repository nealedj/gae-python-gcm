
from gae_python_gcm.gcm import GCMMessage

GCM_API_KEY = 'YOUR_API_KEY'

push_token = 'GCM_REGISTRATION_ID'
notification_payload = {'your-key': 'your-value'}

gcm_message = GCMMessage(GCM_API_KEY, push_token, notification_payload)
gcm_message.send_message()
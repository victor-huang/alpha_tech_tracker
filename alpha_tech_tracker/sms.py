import os

from twilio.rest import Client

account_sid = os.environ.get('TWILIO_ACCOUNT_ID')
auth_token = os.environ.get('TWILIO_AUTH_TOKEN')

if not account_sid and not auth_token:
    raise ValueError('ENVs TWILIO_ACCOUNT_ID and TWILIO_AUTH_TOKEN must be set.')
client = Client(account_sid, auth_token)

def send_sms(to_phone_number, msg):

    message = client.messages.create(
        body=msg,
        from_='+12563630551',
        to='+1{}'.format(to_phone_number)
        )

    return message.sid


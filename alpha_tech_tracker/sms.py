import os

from twilio.rest import Client
import subprocess

account_sid = os.environ.get('TWILIO_ACCOUNT_ID')
auth_token = os.environ.get('TWILIO_AUTH_TOKEN')

if not account_sid and not auth_token:
    raise ValueError('ENVs TWILIO_ACCOUNT_ID and TWILIO_AUTH_TOKEN must be set.')
client = Client(account_sid, auth_token)

script_path = os.path.abspath(__file__)
script_dir = os.path.dirname(script_path)


def send_sms(to_phone_number, msg):

    message = client.messages.create(
        body=msg,
        from_='+12563630551',
        to='+1{}'.format(to_phone_number)
        )

    return message.sid


def send_sms_via_imessage(to_phone_number, msg):
    """
    this method only works on macOS with the Messages App active
    """
    script = os.path.join(script_dir, 'imessage/send_imessage.scpt')
    subprocess.call(["osascript", script, to_phone_number, msg])

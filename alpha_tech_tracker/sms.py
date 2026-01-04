import os

from twilio.rest import Client
import subprocess

script_path = os.path.abspath(__file__)
script_dir = os.path.dirname(script_path)

# Lazy initialization - client is only created when needed
_client = None


def _get_twilio_client():
    """Get or create the Twilio client."""
    global _client
    if _client is None:
        account_sid = os.environ.get('TWILIO_ACCOUNT_ID')
        auth_token = os.environ.get('TWILIO_AUTH_TOKEN')

        if not account_sid or not auth_token:
            raise ValueError(
                'ENVs TWILIO_ACCOUNT_ID and TWILIO_AUTH_TOKEN must be set to send SMS. '
                'If you do not need SMS notifications, this is optional.'
            )
        _client = Client(account_sid, auth_token)
    return _client


def send_sms(to_phone_number, msg):
    """Send SMS via Twilio. Requires TWILIO_ACCOUNT_ID and TWILIO_AUTH_TOKEN env vars."""
    client = _get_twilio_client()
    message = client.messages.create(
        body=msg,
        from_='+14086101618',
        to='+1{}'.format(to_phone_number)
    )
    return message.sid


def send_sms_via_imessage(to_phone_number, msg):
    """
    this method only works on macOS with the Messages App active
    """
    script = os.path.join(script_dir, 'imessage/send_imessage.scpt')
    subprocess.call(["osascript", script, to_phone_number, msg])

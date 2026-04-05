import json
import logging
import os
import re
from datetime import datetime

import requests

from alpha_tech_tracker.op_momentum_strategy.op_momentum_selector import DEFAULT_TICKERS

from .models import _D

logger = logging.getLogger(__name__)

TICKERS = DEFAULT_TICKERS
ACCOUNT_BUDGET = 25_000
MAX_ACTIVE_SYMBOLS = 2
OPENING_BARS = 3
OPENING_START_TIME = "09:30"
STOP_PCT = _D("0.15")
STRIKE_CALL_OFFSET = _D("0.90")
STRIKE_PUT_OFFSET = _D("1.10")
CAPITAL_PER_SYMBOL = _D("0.45")
EOD_EXIT_TIME = "15:55"
MA_WARMUP_DAYS = 7
ROLLING_LOOKBACK_DAYS = 30
BEARISH_MA200 = False
SIGNAL_BUFFER_MINUTES = 2
TRAILING_MA = "ma20"
MAX_LOSS_PCT = None
ARMED_MA20_EXIT = False
REGIME_FILTER = False
REGIME_MA = 5
RANK_WEIGHTED_SIZING = False
RANK_WEIGHTS = [0.50, 0.30, 0.20]

_clicksend_cfg: dict = {}

_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")


def _load_config(config_file: str = _CONFIG_FILE):
    """
    Load credentials from config.json and inject them into the environment
    for any key not already set. Environment variables always take precedence.

    Config file format (alpha_tech_tracker/op_momentum_strategy/config.json):
        {
          "alpaca": {
            "api_key": "YOUR_KEY",
            "secret_key": "YOUR_SECRET"
          }
        }
    """
    if not os.path.exists(config_file):
        return

    with open(config_file) as f:
        cfg = json.load(f)

    alpaca = cfg.get("alpaca", {})
    mapping = {
        "api_key": "ALPACA_API_KEY",
        "secret_key": "ALPACA_SECRET_KEY",
    }
    for cfg_key, env_key in mapping.items():
        if alpaca.get(cfg_key) and not os.environ.get(env_key):
            os.environ[env_key] = alpaca[cfg_key]

    _clicksend_cfg.clear()
    _clicksend_cfg.update(cfg.get("clicksend", {}))

    telegram = cfg.get("telegram", {})
    if telegram.get("bot_token"):
        _clicksend_cfg["telegram_bot_token"] = telegram["bot_token"]
    if telegram.get("chat_id"):
        _clicksend_cfg["telegram_chat_id"] = telegram["chat_id"]


def _send_telegram(message: str):
    token = _clicksend_cfg.get("telegram_bot_token")
    chat_id = _clicksend_cfg.get("telegram_chat_id")
    if not token or not chat_id:
        logger.debug("Telegram skipped — bot_token or chat_id missing")
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=10)
        logger.info("Telegram sent: %s", message)
    except Exception:
        logger.warning("Telegram failed", exc_info=True)


def _send_sms(message: str):
    if not _clicksend_cfg.get("enabled"):
        return
    username = _clicksend_cfg.get("username")
    api_key = _clicksend_cfg.get("api_key")
    to_num = _clicksend_cfg.get("to_number")
    if not all([username, api_key, to_num]):
        logger.debug("SMS skipped — clicksend config incomplete")
        return
    try:
        import clicksend_client

        configuration = clicksend_client.Configuration()
        configuration.username = username
        configuration.password = api_key
        api = clicksend_client.SMSApi(clicksend_client.ApiClient(configuration))
        sms = clicksend_client.SmsMessageCollection(
            messages=[clicksend_client.SmsMessage(to=to_num, body=message)]
        )
        api.sms_send_post(sms)
        logger.info("SMS sent: %s", message)
    except Exception:
        logger.warning("SMS failed", exc_info=True)


def _fmt_option(symbol: str) -> str:
    """Format an OSI option symbol into a human-readable string.

    e.g. 'NVDA260404C00170000' → 'NVDA Apr 04 Call @ $170'
    """
    m = re.match(r"^([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d{8})$", symbol)
    if not m:
        return symbol
    ticker, yy, mm, dd, cp, strike_raw = m.groups()
    expiry = datetime.strptime(f"20{yy}-{mm}-{dd}", "%Y-%m-%d")
    option_type = "Call" if cp == "C" else "Put"
    strike = int(strike_raw) / 1000
    strike_str = f"${strike:.0f}" if strike == int(strike) else f"${strike:.2f}"
    return f"{ticker} {expiry.strftime('%b %d')} {option_type} @ {strike_str}"


_notifications_enabled = True


def disable_notifications():
    global _notifications_enabled
    _notifications_enabled = False


def enable_notifications():
    global _notifications_enabled
    _notifications_enabled = True


def _notify(message: str):
    if not _notifications_enabled:
        logger.debug("Notifications disabled — skipping: %s", message)
        return
    _send_sms(message)
    _send_telegram(message)

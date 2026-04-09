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
EXECUTION_BROKER = "alpaca"   # "alpaca" | "etrade"
ETRADE_ACCOUNT_ID = None
ETRADE_SANDBOX = False
_ETRADE_SESSION_TOKENS: dict = {}
ACCOUNT_BUDGET = 25_000
MAX_ACTIVE_SYMBOLS = 2
OPENING_BARS = 3
OPENING_START_TIME = "09:30"
STOP_PCT = _D("0.15")
STRIKE_CALL_OFFSET = _D("0.90")
STRIKE_PUT_OFFSET = _D("1.10")
MAX_CAPITAL_PERCENTAGE_PER_SYMBOL_IN_WINDOW = _D("0.45")
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
    Load credentials and broker settings from config.json.

    Environment variables always take precedence over the config file.

    Config file format (alpha_tech_tracker/op_momentum_strategy/config.json):
        {
          "execution_broker": "alpaca",   // "alpaca" (default) | "etrade"
          "alpaca": {
            "api_key": "YOUR_KEY",
            "secret_key": "YOUR_SECRET"
          },
          "etrade": {
            "account_id": "712793764",
            "sandbox": false
          },
          "etrade_credentials": {
            "api_key_id": "YOUR_ETRADE_KEY",     // optional — prefer env vars
            "api_secret_key": "YOUR_ETRADE_SECRET"
          }
        }
    """
    global EXECUTION_BROKER, ETRADE_ACCOUNT_ID, ETRADE_SANDBOX

    if not os.path.exists(config_file):
        return

    with open(config_file) as f:
        cfg = json.load(f)

    # Broker selection
    if cfg.get("execution_broker"):
        EXECUTION_BROKER = cfg["execution_broker"]

    # Alpaca credentials → env vars
    alpaca = cfg.get("alpaca", {})
    for cfg_key, env_key in (
        ("api_key", "ALPACA_API_KEY"),
        ("secret_key", "ALPACA_SECRET_KEY"),
    ):
        if alpaca.get(cfg_key) and not os.environ.get(env_key):
            os.environ[env_key] = alpaca[cfg_key]

    # ETrade account config
    etrade = cfg.get("etrade", {})
    if etrade.get("account_id"):
        ETRADE_ACCOUNT_ID = str(etrade["account_id"])
    if "sandbox" in etrade:
        ETRADE_SANDBOX = bool(etrade["sandbox"])

    # ETrade stored session tokens
    _ETRADE_SESSION_TOKENS.clear()
    _ETRADE_SESSION_TOKENS.update(cfg.get("etrade_session", {}))

    # ETrade credentials → env vars (prefer env vars set externally)
    etrade_creds = cfg.get("etrade_credentials", {})
    for cfg_key, env_key in (
        ("api_key_id", "ETRADE_API_KEY_ID"),
        ("api_secret_key", "ETRADE_API_SECRET_KEY"),
    ):
        if etrade_creds.get(cfg_key) and not os.environ.get(env_key):
            os.environ[env_key] = etrade_creds[cfg_key]

    _clicksend_cfg.clear()
    _clicksend_cfg.update(cfg.get("clicksend", {}))

    telegram = cfg.get("telegram", {})
    if telegram.get("bot_token"):
        _clicksend_cfg["telegram_bot_token"] = telegram["bot_token"]
    if telegram.get("chat_id"):
        _clicksend_cfg["telegram_chat_id"] = telegram["chat_id"]


def _save_etrade_session_tokens(
    oauth_token: str,
    oauth_token_secret: str,
    config_file: str = _CONFIG_FILE,
):
    """Persist ETrade OAuth tokens to config.json so the engine can reuse them."""
    cfg = {}
    if os.path.exists(config_file):
        with open(config_file) as f:
            cfg = json.load(f)
    cfg["etrade_session"] = {
        "oauth_token": oauth_token,
        "oauth_token_secret": oauth_token_secret,
    }
    tmp = config_file + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, config_file)
    logger.info("ETrade session tokens saved to %s", config_file)


def build_execution_client(is_paper: bool = True):
    """
    Construct and return an ExecutionClient based on EXECUTION_BROKER.

    "alpaca": returns AlpacaAPIClient; is_paper controls paper vs live account.
    "etrade": returns EtradeAPIClient and calls authorize_session() to complete
              the OAuth flow (interactive — opens browser and prompts for token).

    Call _load_config() before this function so EXECUTION_BROKER and ETrade
    account settings are populated.
    """
    if EXECUTION_BROKER == "etrade":
        from alpha_tech_tracker.trade_api.etrade.client import EtradeAPIClient
        client = EtradeAPIClient(
            selected_account_id=ETRADE_ACCOUNT_ID,
            is_sandbox_enabled=ETRADE_SANDBOX,
        )
        if _ETRADE_SESSION_TOKENS.get("oauth_token"):
            client.restore_session(
                _ETRADE_SESSION_TOKENS["oauth_token"],
                _ETRADE_SESSION_TOKENS["oauth_token_secret"],
            )
            if client.verify_session():
                logger.info("ETrade session restored from stored tokens")
                return client
            logger.warning(
                "Stored ETrade session is expired — run etrade_auth.py to renew"
            )
        client.authorize_session()
        return client

    from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient
    return AlpacaAPIClient(is_paper_trading=is_paper)


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
    return f"{ticker} {expiry.strftime('%b %d')} {option_type} (k={strike_str})"


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

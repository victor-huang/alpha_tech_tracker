import json
import sys
import threading
from unittest.mock import MagicMock, patch

import alpha_tech_tracker.op_momentum_strategy.config as config_module
from alpha_tech_tracker.op_momentum_strategy.config import (
    _notify,
    _send_telegram,
    _load_config,
    _fmt_option,
    _save_etrade_session_tokens,
    _save_tradestation_session_tokens,
    build_execution_client,
    disable_notifications,
    enable_notifications,
)
from alpha_tech_tracker.op_momentum_strategy.op_momentum_trade_engine import parse_args

_REQUESTS_POST_PATH = "alpha_tech_tracker.op_momentum_strategy.config.requests"


class TestSendTelegram:
    def setup_method(self):
        config_module._clicksend_cfg.clear()

    def test_sends_message_with_correct_payload(self):
        config_module._clicksend_cfg.update(
            {"telegram_bot_token": "test-token", "telegram_chat_id": "12345"}
        )
        mock_requests = MagicMock()
        with patch(_REQUESTS_POST_PATH, mock_requests):
            _send_telegram("hello from test")

        mock_requests.post.assert_called_once_with(
            "https://api.telegram.org/bottest-token/sendMessage",
            json={"chat_id": "12345", "text": "hello from test"},
            timeout=10,
        )

    def test_skips_when_token_missing(self):
        config_module._clicksend_cfg.update({"telegram_chat_id": "12345"})
        mock_requests = MagicMock()
        with patch(_REQUESTS_POST_PATH, mock_requests):
            _send_telegram("hello")

        mock_requests.post.assert_not_called()

    def test_skips_when_chat_id_missing(self):
        config_module._clicksend_cfg.update({"telegram_bot_token": "test-token"})
        mock_requests = MagicMock()
        with patch(_REQUESTS_POST_PATH, mock_requests):
            _send_telegram("hello")

        mock_requests.post.assert_not_called()

    def test_skips_when_config_empty(self):
        mock_requests = MagicMock()
        with patch(_REQUESTS_POST_PATH, mock_requests):
            _send_telegram("hello")

        mock_requests.post.assert_not_called()

    def test_swallows_request_exception(self):
        config_module._clicksend_cfg.update(
            {"telegram_bot_token": "test-token", "telegram_chat_id": "12345"}
        )
        mock_requests = MagicMock()
        mock_requests.post.side_effect = Exception("network error")
        with patch(_REQUESTS_POST_PATH, mock_requests):
            _send_telegram("hello")  # must not raise


class TestNotify:
    def setup_method(self):
        config_module._clicksend_cfg.clear()
        enable_notifications()

    def teardown_method(self, _):
        enable_notifications()

    def test_calls_both_sms_and_telegram(self):
        with patch(
            "alpha_tech_tracker.op_momentum_strategy.config._send_sms"
        ) as mock_sms, patch(
            "alpha_tech_tracker.op_momentum_strategy.config._send_telegram"
        ) as mock_telegram:
            _notify("trade alert")

        mock_sms.assert_called_once_with("trade alert")
        mock_telegram.assert_called_once_with("trade alert")

    def test_skips_both_when_notifications_disabled(self):
        disable_notifications()
        with patch(
            "alpha_tech_tracker.op_momentum_strategy.config._send_sms"
        ) as mock_sms, patch(
            "alpha_tech_tracker.op_momentum_strategy.config._send_telegram"
        ) as mock_telegram:
            _notify("should not send")

        mock_sms.assert_not_called()
        mock_telegram.assert_not_called()

    def test_resumes_after_enable_notifications(self):
        disable_notifications()
        enable_notifications()
        with patch(
            "alpha_tech_tracker.op_momentum_strategy.config._send_sms"
        ) as mock_sms, patch(
            "alpha_tech_tracker.op_momentum_strategy.config._send_telegram"
        ) as mock_telegram:
            _notify("should send again")

        mock_sms.assert_called_once_with("should send again")
        mock_telegram.assert_called_once_with("should send again")


_BASE_ARGV = ["run", "--window", "M1", "09:30", "3", "--morning-split", "100"]


class TestNoNotifyFlag:
    def setup_method(self):
        enable_notifications()

    def teardown_method(self, _):
        enable_notifications()

    def test_no_notify_flag_parsed_as_true(self):
        with patch.object(sys, "argv", ["prog"] + _BASE_ARGV + ["--no-notify"]):
            args = parse_args()
        assert args.no_notify is True

    def test_no_notify_absent_defaults_to_false(self):
        with patch.object(sys, "argv", ["prog"] + _BASE_ARGV):
            args = parse_args()
        assert args.no_notify is False

    def test_no_notify_flag_disables_both_sms_and_telegram(self):
        with patch.object(sys, "argv", ["prog"] + _BASE_ARGV + ["--no-notify"]):
            args = parse_args()
        if args.no_notify:
            disable_notifications()

        with patch("alpha_tech_tracker.op_momentum_strategy.config._send_sms") as mock_sms, \
             patch("alpha_tech_tracker.op_momentum_strategy.config._send_telegram") as mock_telegram:
            _notify("should be suppressed")

        mock_sms.assert_not_called()
        mock_telegram.assert_not_called()


class TestLoadConfigTelegram:
    def setup_method(self):
        config_module._clicksend_cfg.clear()

    def test_loads_telegram_token_and_chat_id(self, tmp_path):
        cfg = {"telegram": {"bot_token": "tok123", "chat_id": "999"}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(cfg))

        _load_config(str(config_file))

        assert config_module._clicksend_cfg["telegram_bot_token"] == "tok123"
        assert config_module._clicksend_cfg["telegram_chat_id"] == "999"

    def test_skips_telegram_when_section_absent(self, tmp_path):
        cfg = {"alpaca": {"api_key": "k", "secret_key": "s"}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(cfg))

        _load_config(str(config_file))

        assert "telegram_bot_token" not in config_module._clicksend_cfg
        assert "telegram_chat_id" not in config_module._clicksend_cfg

    def test_skips_telegram_when_token_empty(self, tmp_path):
        cfg = {"telegram": {"bot_token": "", "chat_id": "999"}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(cfg))

        _load_config(str(config_file))

        assert "telegram_bot_token" not in config_module._clicksend_cfg


class TestLoadConfigBrokerSettings:
    def setup_method(self):
        config_module.EXECUTION_BROKER = "alpaca"
        config_module.ETRADE_ACCOUNT_ID = None
        config_module.ETRADE_SANDBOX = False
        config_module._ETRADE_SESSION_TOKENS.clear()

    def teardown_method(self, _):
        config_module.EXECUTION_BROKER = "alpaca"
        config_module.ETRADE_ACCOUNT_ID = None
        config_module.ETRADE_SANDBOX = False
        config_module._ETRADE_SESSION_TOKENS.clear()

    def test_sets_execution_broker_from_config(self, tmp_path):
        cfg = {"execution_broker": "etrade"}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(cfg))

        _load_config(str(config_file))

        assert config_module.EXECUTION_BROKER == "etrade"

    def test_defaults_to_alpaca_when_key_absent(self, tmp_path):
        cfg = {"alpaca": {"api_key": "k", "secret_key": "s"}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(cfg))

        _load_config(str(config_file))

        assert config_module.EXECUTION_BROKER == "alpaca"

    def test_sets_etrade_account_id(self, tmp_path):
        cfg = {"etrade": {"account_id": "712793764"}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(cfg))

        _load_config(str(config_file))

        assert config_module.ETRADE_ACCOUNT_ID == "712793764"

    def test_sets_etrade_sandbox_flag(self, tmp_path):
        cfg = {"etrade": {"account_id": "123", "sandbox": True}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(cfg))

        _load_config(str(config_file))

        assert config_module.ETRADE_SANDBOX is True

    def test_etrade_credentials_injected_into_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ETRADE_API_KEY_ID", raising=False)
        monkeypatch.delenv("ETRADE_API_SECRET_KEY", raising=False)
        cfg = {
            "etrade_credentials": {
                "api_key_id": "MY_ETRADE_KEY",
                "api_secret_key": "MY_ETRADE_SECRET",
            }
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(cfg))

        _load_config(str(config_file))

        import os
        assert os.environ["ETRADE_API_KEY_ID"] == "MY_ETRADE_KEY"
        assert os.environ["ETRADE_API_SECRET_KEY"] == "MY_ETRADE_SECRET"

    def test_env_var_takes_precedence_over_etrade_credentials(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ETRADE_API_KEY_ID", "ENV_KEY")
        cfg = {"etrade_credentials": {"api_key_id": "CFG_KEY"}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(cfg))

        _load_config(str(config_file))

        import os
        assert os.environ["ETRADE_API_KEY_ID"] == "ENV_KEY"

    def test_loads_etrade_session_tokens(self, tmp_path):
        cfg = {
            "etrade_session": {
                "oauth_token": "tok_abc",
                "oauth_token_secret": "sec_xyz",
            }
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(cfg))

        _load_config(str(config_file))

        assert config_module._ETRADE_SESSION_TOKENS["oauth_token"] == "tok_abc"
        assert config_module._ETRADE_SESSION_TOKENS["oauth_token_secret"] == "sec_xyz"

    def test_clears_stale_session_tokens_when_section_absent(self, tmp_path):
        config_module._ETRADE_SESSION_TOKENS.update(
            {"oauth_token": "old", "oauth_token_secret": "old_sec"}
        )
        cfg = {"alpaca": {"api_key": "k", "secret_key": "s"}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(cfg))

        _load_config(str(config_file))

        assert config_module._ETRADE_SESSION_TOKENS == {}


class TestSaveEtradeSessionTokens:
    def test_writes_tokens_to_config_json(self, tmp_path):
        config_file = tmp_path / "config.json"

        _save_etrade_session_tokens("tok_abc", "sec_xyz", config_file=str(config_file))

        with open(config_file) as f:
            saved = json.load(f)
        assert saved["etrade_session"]["oauth_token"] == "tok_abc"
        assert saved["etrade_session"]["oauth_token_secret"] == "sec_xyz"

    def test_merges_with_existing_config(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"execution_broker": "etrade"}))

        _save_etrade_session_tokens("tok", "sec", config_file=str(config_file))

        with open(config_file) as f:
            saved = json.load(f)
        assert saved["execution_broker"] == "etrade"
        assert saved["etrade_session"]["oauth_token"] == "tok"

    def test_overwrites_existing_session_tokens(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(
            json.dumps({"etrade_session": {"oauth_token": "old", "oauth_token_secret": "old_s"}})
        )

        _save_etrade_session_tokens("new_tok", "new_sec", config_file=str(config_file))

        with open(config_file) as f:
            saved = json.load(f)
        assert saved["etrade_session"]["oauth_token"] == "new_tok"


class TestBuildExecutionClient:
    def setup_method(self):
        config_module.EXECUTION_BROKER = "alpaca"
        config_module.ETRADE_ACCOUNT_ID = None
        config_module.ETRADE_SANDBOX = False
        config_module._ETRADE_SESSION_TOKENS.clear()

    def teardown_method(self, _):
        config_module.EXECUTION_BROKER = "alpaca"
        config_module._ETRADE_SESSION_TOKENS.clear()

    def test_returns_alpaca_client_by_default(self):
        from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient
        client = build_execution_client(is_paper=True)
        assert isinstance(client, AlpacaAPIClient)
        assert client._is_paper_trading is True

    def test_alpaca_paper_flag_passed_through(self):
        from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient
        client = build_execution_client(is_paper=False)
        assert isinstance(client, AlpacaAPIClient)
        assert client._is_paper_trading is False

    def test_returns_etrade_client_when_broker_is_etrade(self):
        from alpha_tech_tracker.trade_api.etrade.client import EtradeAPIClient
        config_module.EXECUTION_BROKER = "etrade"
        config_module.ETRADE_ACCOUNT_ID = "712793764"
        config_module.ETRADE_SANDBOX = True

        with patch.object(EtradeAPIClient, "authorize_session"):
            client = build_execution_client(is_paper=True)

        assert isinstance(client, EtradeAPIClient)
        assert client._selected_account_id == "712793764"
        assert client._base_url_host == "apisb.etrade.com"

    def test_etrade_calls_authorize_session(self):
        from alpha_tech_tracker.trade_api.etrade.client import EtradeAPIClient
        config_module.EXECUTION_BROKER = "etrade"

        with patch.object(EtradeAPIClient, "authorize_session") as mock_auth:
            build_execution_client()

        mock_auth.assert_called_once()

    def test_etrade_uses_stored_session_without_oauth_when_valid(self):
        from alpha_tech_tracker.trade_api.etrade.client import EtradeAPIClient
        config_module.EXECUTION_BROKER = "etrade"
        config_module._ETRADE_SESSION_TOKENS.update(
            {"oauth_token": "stored_tok", "oauth_token_secret": "stored_sec"}
        )

        with patch.object(EtradeAPIClient, "restore_session") as mock_restore, \
             patch.object(EtradeAPIClient, "verify_session", return_value=True), \
             patch.object(EtradeAPIClient, "authorize_session") as mock_auth:
            build_execution_client()

        mock_restore.assert_called_once_with("stored_tok", "stored_sec")
        mock_auth.assert_not_called()

    def test_etrade_falls_back_to_oauth_when_stored_session_expired(self):
        from alpha_tech_tracker.trade_api.etrade.client import EtradeAPIClient
        config_module.EXECUTION_BROKER = "etrade"
        config_module._ETRADE_SESSION_TOKENS.update(
            {"oauth_token": "expired_tok", "oauth_token_secret": "expired_sec"}
        )

        with patch.object(EtradeAPIClient, "restore_session"), \
             patch.object(EtradeAPIClient, "verify_session", return_value=False), \
             patch.object(EtradeAPIClient, "authorize_session") as mock_auth:
            build_execution_client()

        mock_auth.assert_called_once()

    def test_broker_param_overrides_global_execution_broker(self):
        from alpha_tech_tracker.trade_api.etrade.client import EtradeAPIClient
        config_module.EXECUTION_BROKER = "alpaca"

        with patch.object(EtradeAPIClient, "authorize_session"):
            client = build_execution_client(broker="etrade")

        assert isinstance(client, EtradeAPIClient)

    def test_broker_param_alpaca_overrides_global_tradestation(self):
        from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient
        config_module.EXECUTION_BROKER = "tradestation"

        client = build_execution_client(is_paper=True, broker="alpaca")

        assert isinstance(client, AlpacaAPIClient)

    def test_broker_param_none_falls_back_to_global_execution_broker(self):
        from alpha_tech_tracker.trade_api.alpaca_client.client import AlpacaAPIClient
        config_module.EXECUTION_BROKER = "alpaca"

        client = build_execution_client(broker=None)

        assert isinstance(client, AlpacaAPIClient)

    def test_broker_param_tradestation_uses_stored_session(self):
        from alpha_tech_tracker.trade_api.tradestation.client import TradeStationAPIClient
        config_module.EXECUTION_BROKER = "alpaca"
        config_module._TRADESTATION_SESSION_TOKENS.update({"access_token": "tok"})

        with patch.object(TradeStationAPIClient, "restore_session"), \
             patch.object(TradeStationAPIClient, "verify_session", return_value=True):
            client = build_execution_client(broker="tradestation")

        assert isinstance(client, TradeStationAPIClient)
        config_module._TRADESTATION_SESSION_TOKENS.clear()


class TestFmtOption:
    """Issue 3: _fmt_option must label the strike as strike price, not fill price."""

    def test_strike_labeled_with_k_prefix_not_at_symbol(self):
        result = _fmt_option("NVDA260404C00170000")
        assert "(k=$170)" in result
        assert "@ $170" not in result

    def test_call_option_contains_ticker_expiry_and_type(self):
        result = _fmt_option("NVDA260404C00170000")
        assert "NVDA" in result
        assert "Apr 04" in result
        assert "Call" in result

    def test_put_option_contains_correct_type(self):
        result = _fmt_option("SNDK260410P00677500")
        assert "Put" in result
        assert "(k=$677.50)" in result

    def test_whole_dollar_strike_omits_decimal(self):
        result = _fmt_option("TSLA260411C00325000")
        assert "(k=$325)" in result
        assert "325.00" not in result

    def test_fractional_strike_shows_two_decimal_places(self):
        result = _fmt_option("AAPL260411C00222500")
        assert "(k=$222.50)" in result

    def test_unrecognised_symbol_returned_unchanged(self):
        assert _fmt_option("bad-symbol") == "bad-symbol"


class TestSaveTradeStationSessionTokens:
    def test_persists_token_to_config_file(self, tmp_path):
        config_file = str(tmp_path / "config.json")
        token = {"access_token": "abc", "refresh_token": "xyz"}

        _save_tradestation_session_tokens(token, config_file=config_file)

        with open(config_file) as f:
            saved = json.load(f)
        assert saved["tradestation_session"] == token

    def test_merges_with_existing_config_keys(self, tmp_path):
        config_file = str(tmp_path / "config.json")
        with open(config_file, "w") as f:
            json.dump({"execution_broker": "tradestation"}, f)
        token = {"access_token": "new"}

        _save_tradestation_session_tokens(token, config_file=config_file)

        with open(config_file) as f:
            saved = json.load(f)
        assert saved["execution_broker"] == "tradestation"
        assert saved["tradestation_session"] == token

    def test_concurrent_writes_do_not_raise(self, tmp_path):
        # BUG-2: concurrent token_updater callbacks from multiple TS stream threads
        # caused a FileNotFoundError on os.replace() due to race on the .tmp file.
        config_file = str(tmp_path / "config.json")
        errors = []

        def write_token(i):
            try:
                _save_tradestation_session_tokens(
                    {"access_token": f"tok{i}"},
                    config_file=config_file,
                )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=write_token, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent writes raised: {errors}"
        with open(config_file) as f:
            saved = json.load(f)
        assert "tradestation_session" in saved

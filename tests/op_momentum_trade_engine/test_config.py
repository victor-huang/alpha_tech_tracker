import json
from unittest.mock import MagicMock, patch


import alpha_tech_tracker.op_momentum_strategy.config as config_module
from alpha_tech_tracker.op_momentum_strategy.config import (
    _notify,
    _send_telegram,
    _load_config,
    _fmt_option,
    disable_notifications,
    enable_notifications,
)

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

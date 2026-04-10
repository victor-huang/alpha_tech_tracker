"""TradeStation OAuth 2.0 authentication helper.

Run once to authorize and store tokens. Refresh tokens last indefinitely —
re-run only if the refresh token is revoked or the session cannot be restored.

Usage:
    # Authorize and store tokens (opens browser — callback captured automatically)
    python -m alpha_tech_tracker.op_momentum_strategy.tradestation_auth

    # Check whether stored tokens are still valid
    python -m alpha_tech_tracker.op_momentum_strategy.tradestation_auth --verify

    # Use simulation environment instead of live
    python -m alpha_tech_tracker.op_momentum_strategy.tradestation_auth --sim
"""

import argparse
import logging
import sys

from .config import (
    TRADESTATION_ACCOUNT_KEY,
    TRADESTATION_ENVIRONMENT,
    _CONFIG_FILE,
    _TRADESTATION_SESSION_TOKENS,
    _load_config,
    _save_tradestation_session_tokens,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _authorize(account_key, environment: str) -> None:
    from alpha_tech_tracker.trade_api.tradestation.client import TradeStationAPIClient

    client = TradeStationAPIClient(
        selected_account_key=account_key,
        environment=environment,
    )
    token = client.authorize_session()
    _save_tradestation_session_tokens(token)
    print(f"\nTokens saved to {_CONFIG_FILE}")
    print("You can now start the trade engine — it will reuse this session.")


def _verify(account_key, environment: str) -> bool:
    from alpha_tech_tracker.trade_api.tradestation.client import TradeStationAPIClient

    stored = _TRADESTATION_SESSION_TOKENS
    if not stored.get("access_token"):
        print("No stored TradeStation session found in config.json.")
        print("Run without --verify to authorize and store tokens.")
        return False

    client = TradeStationAPIClient(
        selected_account_key=account_key,
        environment=environment,
    )
    client.restore_session(stored)

    if client.verify_session():
        print("Stored TradeStation session is valid — engine can start without re-auth.")
        return True

    print("Stored TradeStation session has expired.")
    print("Run without --verify to authorize and store fresh tokens.")
    return False


def main():
    parser = argparse.ArgumentParser(
        description="TradeStation OAuth 2.0 authentication helper for the trade engine.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Check if stored tokens are valid without opening a browser",
    )
    parser.add_argument(
        "--sim",
        action="store_true",
        help="Use TradeStation simulation environment",
    )
    parser.add_argument(
        "--account-key",
        default=None,
        help="TradeStation account key (overrides config.json)",
    )
    args = parser.parse_args()

    _load_config()

    environment = "sim" if args.sim else TRADESTATION_ENVIRONMENT
    account_key = args.account_key or TRADESTATION_ACCOUNT_KEY

    if args.verify:
        ok = _verify(account_key, environment)
        sys.exit(0 if ok else 1)

    _authorize(account_key, environment)


if __name__ == "__main__":
    main()

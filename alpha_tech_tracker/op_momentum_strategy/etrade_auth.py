"""ETrade OAuth authentication helper.

Run this once before starting the live engine with ETrade as broker.
Tokens are valid for the current trading day and expire at midnight ET.

Usage:
    # Authorize and store tokens (opens browser)
    python -m alpha_tech_tracker.op_momentum_strategy.etrade_auth

    # Check whether stored tokens are still valid (no browser needed)
    python -m alpha_tech_tracker.op_momentum_strategy.etrade_auth --verify

    # Use sandbox environment instead of production
    python -m alpha_tech_tracker.op_momentum_strategy.etrade_auth --sandbox
"""

import argparse
import logging
import sys

from .config import (
    ETRADE_ACCOUNT_ID,
    ETRADE_SANDBOX,
    _CONFIG_FILE,
    _ETRADE_SESSION_TOKENS,
    _load_config,
    _save_etrade_session_tokens,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _authorize(account_id, sandbox: bool) -> None:
    """Run the full OAuth browser flow and save tokens to config.json."""
    from alpha_tech_tracker.trade_api.etrade.client import EtradeAPIClient

    client = EtradeAPIClient(
        selected_account_id=account_id,
        is_sandbox_enabled=sandbox,
    )
    print(
        "\nStarting ETrade OAuth flow — your browser will open.\n"
        "Log in, authorize the app, and paste the verification code below.\n"
    )
    token_info = client.authorize_session()

    _save_etrade_session_tokens(
        oauth_token=token_info["oauth_token"],
        oauth_token_secret=token_info["oauth_token_secret"],
    )
    print(f"\nTokens saved to {_CONFIG_FILE}")
    print("You can now start the trade engine — it will reuse this session.")


def _verify(account_id, sandbox: bool) -> bool:
    """Check whether stored tokens are still valid. Returns True if valid."""
    from alpha_tech_tracker.trade_api.etrade.client import EtradeAPIClient

    stored = _ETRADE_SESSION_TOKENS
    if not stored.get("oauth_token"):
        print("No stored ETrade session found in config.json.")
        print("Run without --verify to authorize and store tokens.")
        return False

    client = EtradeAPIClient(
        selected_account_id=account_id,
        is_sandbox_enabled=sandbox,
    )
    client.restore_session(
        oauth_token=stored["oauth_token"],
        oauth_token_secret=stored["oauth_token_secret"],
    )

    if client.verify_session():
        print("Stored ETrade session is valid — engine can start without re-auth.")
        return True

    print("Stored ETrade session has expired.")
    print("Run without --verify to authorize and store fresh tokens.")
    return False


def main():
    parser = argparse.ArgumentParser(
        description="ETrade OAuth authentication helper for the trade engine.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Check if stored tokens are valid without opening a browser",
    )
    parser.add_argument(
        "--sandbox",
        action="store_true",
        help="Use ETrade sandbox environment",
    )
    parser.add_argument(
        "--account-id",
        default=None,
        help="ETrade account ID (overrides config.json)",
    )
    args = parser.parse_args()

    _load_config()

    sandbox = args.sandbox or ETRADE_SANDBOX
    account_id = args.account_id or ETRADE_ACCOUNT_ID

    if args.verify:
        ok = _verify(account_id, sandbox)
        sys.exit(0 if ok else 1)

    _authorize(account_id, sandbox)


if __name__ == "__main__":
    main()

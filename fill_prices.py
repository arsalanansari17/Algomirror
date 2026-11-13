"""Fill the shared daily-close store by hand.

    python fill_prices.py          # only inside the evening window (15:40-16:10 IST, weekdays)
    python fill_prices.py --now    # any time: for the first backfill, at an hour the source
                                   # account is not trading. One call at a time with a pause.

The same pass runs by itself at 15:45 IST when PRICE_FILLER_ENABLED=1.
"""
import sys

from app import create_app
from app.utils import price_filler


def main() -> int:
    force = "--now" in sys.argv[1:]
    app = create_app(start_background_services=False)
    with app.app_context():
        account = price_filler.source_account()
        if account is None:
            print("No active source account (set PRICE_SOURCE_ACCOUNT_ID or mark one primary).")
            return 1
        print(f"Source account: {account.account_name} ({account.host_url})")
        summary = price_filler.run(price_filler.make_fetcher(account), force=force)
        print(summary)
        return 0 if not summary["stopped"] or summary["stopped"] == "outside the window" else 2


if __name__ == "__main__":
    sys.exit(main())

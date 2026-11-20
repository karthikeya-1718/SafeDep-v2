"""Client application utilizing Payment & Account Services API."""

from old_library import (
    execute_query,
    fetch_user_profile,
    format_invoice,
    set_notification_channel,
)


def run_billing_tasks(user_id: int):
    # 1. Fetch user profile (old: 1 arg; new: requires 'auth_token')
    user = fetch_user_profile(user_id)
    print("User loaded:", user["name"])

    # 2. Run database query (old: passed timeout=10; new: 'timeout' removed)
    results = execute_query("SELECT * FROM transactions", timeout=10)
    print("Transactions fetched:", len(results))

    # 3. Create invoice (old: customer_name, total_amount; new: reordered)
    invoice = format_invoice("Alex", 149.99)
    print("Invoice:", invoice)

    # 4. Set notification channel (old: no args / default 'email'; new: 'channel' required)
    channel = set_notification_channel()
    print("Channel status:", channel)


if __name__ == "__main__":
    run_billing_tasks(42)

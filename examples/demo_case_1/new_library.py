"""Payment & Account Services Library - Version 2.0.0

Signature-level breaking changes introduced:
1. `execute_query`: Parameter 'timeout' removed (handled at connection pool level).
2. `format_invoice`: Positional parameters reordered ('total_amount', 'customer_name').
3. `set_notification_channel`: Default value removed for 'channel' (must be explicitly provided).
4. `fetch_user_profile`: New required parameter 'auth_token' added without default value.
"""

def fetch_user_profile(user_id: int, auth_token: str) -> dict:
    """Fetch user profile by ID (now requires authentication token)."""
    return {"user_id": user_id, "name": "Alex", "plan": "pro", "token": auth_token}


def execute_query(query_str: str) -> list:
    """Execute a database query (timeout configuration removed)."""
    return [{"status": "success", "query": query_str}]


def format_invoice(total_amount: float, customer_name: str) -> str:
    """Format customer invoice text (arguments reordered)."""
    return f"Invoice for {customer_name}: ${total_amount:.2f}"


def set_notification_channel(channel: str) -> str:
    """Configure customer notification channel (channel is now required)."""
    return f"Notifications routed to {channel}"


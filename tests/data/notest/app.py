"""Sample repository without tests containing non-deterministic risky sites."""

import random
import time
from datetime import datetime

_SESSION_CACHE = {}


def process_transaction(user_id: str, amount: float) -> dict:
    """Processes user transaction with shared global cache and clock dependency."""
    global _SESSION_CACHE
    time.sleep(0.01)  # Thread timing susceptibility
    tx_id = f"tx_{random.randint(1000, 9999)}"  # Unseeded random
    created_at = datetime.now().isoformat()  # Clock dependency

    _SESSION_CACHE[tx_id] = {"user_id": user_id, "amount": amount, "timestamp": created_at}
    return {"transaction_id": tx_id, "status": "completed", "cache_size": len(_SESSION_CACHE)}


def get_active_cache() -> dict:
    return _SESSION_CACHE


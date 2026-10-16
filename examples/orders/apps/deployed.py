"""Independently runnable deployed reference HTTP application; settings arrive on stdin."""

from pg_rehearse.rollout.orders_app import serve

if __name__ == "__main__":
    try:
        raise SystemExit(serve("deployed"))
    except Exception:
        raise SystemExit(3) from None

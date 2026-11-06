"""CLI entry: python -m integrations.gmail setup|status|revoke."""

from integrations.gmail.gmail_client import main

if __name__ == "__main__":
    raise SystemExit(main())

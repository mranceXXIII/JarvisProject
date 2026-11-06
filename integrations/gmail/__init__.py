"""Gmail integration package (spec section 11).

OAuth tokens live in the secure credential store, never in files. Sending
email is a HIGH risk action and always passes through the approval system.
"""

__all__ = ["gmail_client", "gmail_tools"]

from broker.schwab.auth.authenticate import get_access_token


# Schwab OAuth token utility: logs in and writes token.json (see README —
# the fallback when the Settings page's Reconnect isn't available).
if __name__ == "__main__":
    get_access_token()

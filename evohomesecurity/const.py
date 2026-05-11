"""Constants for evohomesecurity API library."""

NAME = "evohomesecurity"
VERSION = "1.0.0"

BASE_URL = "https://tc20e.total-connect.eu/applicationservice/domoweb"

# API request limit and delay between requests
RETRY_LIMIT = 6
RETRY_DELAY = 5  # seconds

# Time duration between automatic logout and login
SESSION_RESET_DELAY = 5  # seconds

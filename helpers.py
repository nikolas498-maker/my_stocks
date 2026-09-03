import os
import time
from functools import wraps

import requests
from flask import session, redirect, url_for, flash

# ---------------------------------------------------------------------------
# Ρυθμίσεις API
# ---------------------------------------------------------------------------
# Βάλε το δικό σου δωρεάν API key από https://finnhub.io/register
# είτε εδώ, είτε (καλύτερα) ως environment variable πριν τρέξεις την εφαρμογή:
#   Windows (PowerShell):  $env:FINNHUB_API_KEY = "το_key_σου"
#   macOS/Linux:           export FINNHUB_API_KEY="το_key_σου"
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
FINNHUB_URL = "https://finnhub.io/api/v1/quote"

# Δωρεάν API μετατροπής νομισμάτων, δεν χρειάζεται key
EXCHANGE_URL = "https://api.frankfurter.app/latest"

SUPPORTED_CURRENCIES = ["EUR", "USD", "GBP"]
CURRENCY_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£"}
BASE_CURRENCY = "EUR"  # νόμισμα στο οποίο υπολογίζονται τα συνολικά ποσά

# Απλή cache στη μνήμη ώστε να μη χτυπάμε το API σε κάθε refresh
_price_cache = {}       # {ticker: (timestamp, price_usd)}
_rate_cache = {}        # {(from,to): (timestamp, rate)}
PRICE_CACHE_TTL = 60        # δευτερόλεπτα
RATE_CACHE_TTL = 3600       # δευτερόλεπτα


def login_required(f):
    """Decorator που απαιτεί συνδεδεμένο χρήστη."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


def get_current_price(ticker):
    """
    Επιστρέφει την τρέχουσα τιμή μιας μετοχής σε USD μέσω του Finnhub API.
    Επιστρέφει None αν αποτύχει η κλήση (π.χ. λάθος ticker, δεν υπάρχει key, timeout).
    Χρησιμοποιεί μικρή cache 60 δευτερολέπτων ανά ticker.
    """
    now = time.time()
    cached = _price_cache.get(ticker)
    if cached and now - cached[0] < PRICE_CACHE_TTL:
        return cached[1]

    if not FINNHUB_API_KEY:
        return None

    try:
        response = requests.get(
            FINNHUB_URL,
            params={"symbol": ticker, "token": FINNHUB_API_KEY},
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()
        price = data.get("c")  # current price
        # Το Finnhub επιστρέφει 0 όταν δεν βρίσκει το symbol
        if not price:
            return None
        _price_cache[ticker] = (now, price)
        return price
    except (requests.RequestException, ValueError):
        return None


def get_exchange_rate(from_currency, to_currency):
    """Επιστρέφει την ισοτιμία from_currency -> to_currency. 1.0 αν είναι ίδια."""
    if from_currency == to_currency:
        return 1.0

    now = time.time()
    key = (from_currency, to_currency)
    cached = _rate_cache.get(key)
    if cached and now - cached[0] < RATE_CACHE_TTL:
        return cached[1]

    try:
        response = requests.get(
            EXCHANGE_URL,
            params={"from": from_currency, "to": to_currency},
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()
        rate = data["rates"][to_currency]
        _rate_cache[key] = (now, rate)
        return rate
    except (requests.RequestException, ValueError, KeyError):
        # Αν αποτύχει η κλήση, καλύτερα να μην μπερδέψουμε τα νούμερα
        return None


def convert_currency(amount, from_currency, to_currency):
    """Μετατρέπει ένα ποσό μεταξύ νομισμάτων. Επιστρέφει None αν αποτύχει."""
    if amount is None:
        return None
    rate = get_exchange_rate(from_currency, to_currency)
    if rate is None:
        return None
    return amount * rate


def format_money(amount, currency=BASE_CURRENCY):
    """Μορφοποιεί ένα ποσό με το σύμβολο του νομίσματος, π.χ. 1234.5 -> '1,234.50 €'."""
    if amount is None:
        return "—"
    symbol = CURRENCY_SYMBOLS.get(currency, currency)
    return f"{amount:,.2f} {symbol}"
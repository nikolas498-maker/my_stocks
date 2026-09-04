import os
import time

from functools import wraps

import requests

from flask import session, redirect, url_for


# ---------------------------------------------------------------------------
# Ρυθμίσεις API
# ---------------------------------------------------------------------------

# OANOR ATHEX API
OANOR_API_KEY = os.environ.get("OANOR_API_KEY", "")

OANOR_URL = "https://api.oanor.com/athex-api/v1/quote"


# API μετατροπής νομισμάτων
EXCHANGE_URL = "https://api.frankfurter.app/latest"

SUPPORTED_CURRENCIES = ["EUR", "USD", "GBP"]

CURRENCY_SYMBOLS = {
    "EUR": "€",
    "USD": "$",
    "GBP": "£"
}

BASE_CURRENCY = "EUR"


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_price_cache = {}
_rate_cache = {}

# Κρατάμε την τιμή για 60 δευτερόλεπτα
PRICE_CACHE_TTL = 60

# Κρατάμε την ισοτιμία για 1 ώρα
RATE_CACHE_TTL = 3600


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def login_required(f):
    """Decorator που απαιτεί συνδεδεμένο χρήστη."""

    @wraps(f)
    def decorated_function(*args, **kwargs):

        if session.get("user_id") is None:
            return redirect(url_for("login"))

        return f(*args, **kwargs)

    return decorated_function


# ---------------------------------------------------------------------------
# Stock price
# ---------------------------------------------------------------------------



def get_current_price(ticker):
    """
    Get the current ATHEX stock price from OANOR.
    """

    now = time.time()

    # Check cache
    cached = _price_cache.get(ticker)
    if cached and now - cached[0] < PRICE_CACHE_TTL:
        return cached[1]

    if not OANOR_API_KEY:
        print("OANOR_API_KEY is missing.")
        return None

    # Convert e.g. BELA.AT -> BELA
    symbol = ticker.upper().replace(".AT", "")

    headers = {
        "x-oanor-key": OANOR_API_KEY
    }

    params = {
        "code": symbol
    }

    try:
        response = requests.get(
            OANOR_URL,
            headers=headers,
            params=params,
            timeout=10
        )

        print(f"OANOR URL: {response.url}")
        print(f"OANOR response for {ticker}: {response.text}")

        response.raise_for_status()

        data = response.json()

        # OANOR response:
        # data -> quotes -> first quote -> price
        quotes = data.get("data", {}).get("quotes", [])

        if not quotes:
            print(f"No quote found for {ticker}.")
            return None

        price = quotes[0].get("price")

        if price is None:
            print(f"No price found for {ticker}.")
            return None

        price = float(price)

        # Save to cache
        _price_cache[ticker] = (now, price)

        return price

    except requests.RequestException as e:
        print(f"HTTP error getting price for {ticker}: {e}")

        try:
            print(f"API response: {response.text}")
        except Exception:
            pass

        return None

    except (ValueError, TypeError, KeyError) as e:
        print(f"Error parsing price for {ticker}: {e}")
        return None




# ---------------------------------------------------------------------------
# Currency exchange rate
# ---------------------------------------------------------------------------

def get_exchange_rate(from_currency, to_currency):
    """
    Επιστρέφει την ισοτιμία from_currency -> to_currency.
    """

    from_currency = from_currency.upper()
    to_currency = to_currency.upper()


    # Ίδιο νόμισμα
    if from_currency == to_currency:
        return 1.0


    # -----------------------------------------------------------------------
    # Cache
    # -----------------------------------------------------------------------

    now = time.time()

    key = (from_currency, to_currency)

    cached = _rate_cache.get(key)

    if cached and now - cached[0] < RATE_CACHE_TTL:
        return cached[1]


    # -----------------------------------------------------------------------
    # API request
    # -----------------------------------------------------------------------

    try:

        response = requests.get(
            EXCHANGE_URL,
            params={
                "from": from_currency,
                "to": to_currency
            },
            timeout=5
        )

        response.raise_for_status()

        data = response.json()

        rate = data["rates"][to_currency]

        rate = float(rate)


        # -------------------------------------------------------------------
        # Cache
        # -------------------------------------------------------------------

        _rate_cache[key] = (now, rate)


        return rate


    except (
        requests.exceptions.RequestException,
        ValueError,
        KeyError,
        TypeError
    ) as e:

        print(
            f"Exchange rate error: {e}"
        )

        return None


# ---------------------------------------------------------------------------
# Currency conversion
# ---------------------------------------------------------------------------

def convert_currency(amount, from_currency, to_currency):
    """
    Μετατρέπει ένα ποσό μεταξύ νομισμάτων.
    """

    if amount is None:
        return None


    rate = get_exchange_rate(
        from_currency,
        to_currency
    )


    if rate is None:
        return None


    return amount * rate


# ---------------------------------------------------------------------------
# Money formatting
# ---------------------------------------------------------------------------

def format_money(amount, currency=BASE_CURRENCY):
    """
    Μορφοποιεί ένα ποσό.

    Παράδειγμα:

        1234.5 -> 1,234.50 €
    """

    if amount is None:
        return "—"


    currency = currency.upper()


    symbol = CURRENCY_SYMBOLS.get(
        currency,
        currency
    )


    return f"{amount:,.2f} {symbol}"


def get_current_prices(tickers):
    """
    Get current prices for multiple ATHEX stocks
    using a single OANOR API request.

    Example:
        ["BELA.AT", "EUROB.AT", "MOH.AT"]

    Returns:
        {
            "BELA.AT": 26.82,
            "EUROB.AT": 3.15,
            "MOH.AT": 28.40
        }
    """

    now = time.time()
    prices = {}
    missing_tickers = []

    if not OANOR_API_KEY:
        print("OANOR_API_KEY is missing.")
        return {}

    # ---------------------------------------------------------
    # Check cache first
    # ---------------------------------------------------------

    for ticker in tickers:
        cached = _price_cache.get(ticker)

        if cached and now - cached[0] < PRICE_CACHE_TTL:
            prices[ticker] = cached[1]
        else:
            missing_tickers.append(ticker)

    # Everything was already cached
    if not missing_tickers:
        return prices

    # ---------------------------------------------------------
    # Convert:
    #
    # BELA.AT  -> BELA
    # EUROB.AT -> EUROB
    # MOH.AT   -> MOH
    # ---------------------------------------------------------

    symbols = [
        ticker.upper().replace(".AT", "")
        for ticker in missing_tickers
    ]

    # OANOR supports comma-separated tickers
    codes = ",".join(symbols)

    headers = {
        "x-oanor-key": OANOR_API_KEY
    }

    params = {
        "code": codes
    }

    try:
        response = requests.get(
            OANOR_URL,
            headers=headers,
            params=params,
            timeout=10
        )

        print(f"OANOR URL: {response.url}")
        print(f"OANOR response: {response.text}")

        response.raise_for_status()

        data = response.json()

        quotes = data.get("data", {}).get("quotes", [])

        if not quotes:
            print("OANOR returned no quotes.")
            return prices

        # ---------------------------------------------------------
        # Process all returned quotes
        # ---------------------------------------------------------

        for quote in quotes:

            symbol = quote.get("ticker")
            price = quote.get("price")

            if symbol is None or price is None:
                continue

            symbol = symbol.upper()

            price = float(price)

            # Convert back:
            #
            # BELA -> BELA.AT
            #
            ticker = f"{symbol}.AT"

            prices[ticker] = price

            # Save to cache
            _price_cache[ticker] = (now, price)

        return prices

    except requests.RequestException as e:
        print(f"HTTP error getting prices from OANOR: {e}")

        try:
            print(f"API response: {response.text}")
        except Exception:
            pass

        return prices

    except (ValueError, TypeError, KeyError) as e:
        print(f"Error parsing OANOR response: {e}")
        return prices

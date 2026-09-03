import os
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, render_template, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

from db import get_db, init_db
from helpers import (
    login_required,
    get_current_price,
    convert_currency,
    format_money,
    SUPPORTED_CURRENCIES,
    BASE_CURRENCY,
)

load_dotenv()

app = Flask(__name__)

app.secret_key = os.environ.get("SECRET_KEY")

if not app.secret_key:
    raise RuntimeError("SECRET_KEY is not set.")

init_db()
# Κάνει το format_money διαθέσιμο μέσα στα templates ως φίλτρο: {{ value | money("EUR") }}
app.jinja_env.filters["money"] = format_money


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirmation = request.form.get("confirmation", "")

        if not username or not password:
            flash("Συμπλήρωσε username και κωδικό.", "danger")
            return render_template("register.html")

        if password != confirmation:
            flash("Οι κωδικοί δεν ταιριάζουν.", "danger")
            return render_template("register.html")

        db = get_db()
        existing = db.execute(
            "SELECT id FROM users WHERE username = %s", (username,)
        ).fetchone()
        if existing:
            db.close()
            flash("Το username χρησιμοποιείται ήδη.", "danger")
            return render_template("register.html")

        db.execute(
            "INSERT INTO users (username, hash) VALUES (%s, %s)",
            (username, generate_password_hash(password)),
        )
        db.commit()
        db.close()

        flash("Ο λογαριασμός δημιουργήθηκε! Συνδέσου.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    session.clear()

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username = %s", (username,)
        ).fetchone()
        db.close()

        if user is None or not check_password_hash(user["hash"], password):
            flash("Λάθος username ή κωδικός.", "danger")
            return render_template("login.html")

        session["user_id"] = user["id"]
        session["username"] = user["username"]
        return redirect(url_for("index"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def index():
    db = get_db()
    transactions = db.execute(
        "SELECT * FROM transactions WHERE user_id = %s ORDER BY ticker, buy_date",
        (session["user_id"],),
    ).fetchall()
    db.close()

    # --- Ομαδοποίηση ανά ticker για τη σύνοψη θέσεων (holdings) ---
    holdings = {}
    for t in transactions:
        cost_eur = convert_currency(t["shares"] * t["buy_price"], t["currency"], BASE_CURRENCY)
        h = holdings.setdefault(
            t["ticker"], {"ticker": t["ticker"], "shares": 0.0, "cost_eur": 0.0, "cost_unavailable": False}
        )
        h["shares"] += t["shares"]
        if cost_eur is None:
            h["cost_unavailable"] = True
        else:
            h["cost_eur"] += cost_eur

    total_investment = 0.0
    total_current_value = 0.0
    totals_complete = True  # γίνεται False αν λείψει έστω μια τιμή/ισοτιμία

    for h in holdings.values():
        price_usd = get_current_price(h["ticker"])
        price_eur = convert_currency(price_usd, "USD", BASE_CURRENCY) if price_usd else None

        h["avg_buy_price_eur"] = (h["cost_eur"] / h["shares"]) if h["shares"] else None
        h["current_price_eur"] = price_eur
        h["market_value_eur"] = price_eur * h["shares"] if price_eur is not None else None

        if price_eur is not None and not h["cost_unavailable"]:
            h["profit_loss_eur"] = h["market_value_eur"] - h["cost_eur"]
            h["return_pct"] = (h["profit_loss_eur"] / h["cost_eur"] * 100) if h["cost_eur"] else None
        else:
            h["profit_loss_eur"] = None
            h["return_pct"] = None
            totals_complete = False

        total_investment += h["cost_eur"]
        if h["market_value_eur"] is not None:
            total_current_value += h["market_value_eur"]

    total_profit_loss = (total_current_value - total_investment) if totals_complete else None
    total_return_pct = (
        (total_profit_loss / total_investment * 100) if totals_complete and total_investment else None
    )

    holdings_list = sorted(holdings.values(), key=lambda h: h["ticker"])

    chart_data = {
        "labels": [h["ticker"] for h in holdings_list],
        "market_value": [round(h["market_value_eur"], 2) if h["market_value_eur"] is not None else 0 for h in holdings_list],
        "investment": [round(h["cost_eur"], 2) for h in holdings_list],
    }

    api_key_missing = not os.environ.get("FINNHUB_API_KEY")

    return render_template(
        "index.html",
        transactions=transactions,
        holdings=holdings_list,
        total_investment=total_investment,
        total_current_value=total_current_value if totals_complete else None,
        total_profit_loss=total_profit_loss,
        total_return_pct=total_return_pct,
        chart_data=chart_data,
        api_key_missing=api_key_missing,
        base_currency=BASE_CURRENCY,
    )


@app.route("/add", methods=["GET", "POST"])
@login_required
def add():
    if request.method == "POST":
        ticker = request.form.get("ticker", "").strip().upper()
        shares_raw = request.form.get("shares")
        buy_price_raw = request.form.get("buy_price")
        currency = request.form.get("currency", BASE_CURRENCY)
        buy_date = request.form.get("buy_date")

        errors = []
        if not ticker:
            errors.append("Το ticker είναι υποχρεωτικό.")
        try:
            shares = float(shares_raw)
            if shares <= 0:
                errors.append("Ο αριθμός μετοχών πρέπει να είναι θετικός.")
        except (TypeError, ValueError):
            errors.append("Μη έγκυρος αριθμός μετοχών.")
            shares = None
        try:
            buy_price = float(buy_price_raw)
            if buy_price <= 0:
                errors.append("Η τιμή αγοράς πρέπει να είναι θετική.")
        except (TypeError, ValueError):
            errors.append("Μη έγκυρη τιμή αγοράς.")
            buy_price = None
        if currency not in SUPPORTED_CURRENCIES:
            errors.append("Μη υποστηριζόμενο νόμισμα.")
        if not buy_date:
            errors.append("Η ημερομηνία αγοράς είναι υποχρεωτική.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("add.html", currencies=SUPPORTED_CURRENCIES, form=request.form)

        db = get_db()
        db.execute(
            """INSERT INTO transactions (user_id, ticker, shares, buy_price, currency, buy_date)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (session["user_id"], ticker, shares, buy_price, currency, buy_date),
        )
        db.commit()
        db.close()

        flash(f"Προστέθηκε η αγορά {ticker}.", "success")
        return redirect(url_for("index"))

    return render_template("add.html", currencies=SUPPORTED_CURRENCIES, form={})


@app.route("/edit/<int:transaction_id>", methods=["GET", "POST"])
@login_required
def edit(transaction_id):
    db = get_db()
    transaction = db.execute(
        "SELECT * FROM transactions WHERE id = %s AND user_id = %s",
        (transaction_id, session["user_id"]),
    ).fetchone()

    if transaction is None:
        db.close()
        flash("Η συναλλαγή δεν βρέθηκε.", "danger")
        return redirect(url_for("index"))

    if request.method == "POST":
        ticker = request.form.get("ticker", "").strip().upper()
        currency = request.form.get("currency", BASE_CURRENCY)
        buy_date = request.form.get("buy_date")

        errors = []
        if not ticker:
            errors.append("Το ticker είναι υποχρεωτικό.")
        try:
            shares = float(request.form.get("shares"))
            if shares <= 0:
                errors.append("Ο αριθμός μετοχών πρέπει να είναι θετικός.")
        except (TypeError, ValueError):
            errors.append("Μη έγκυρος αριθμός μετοχών.")
            shares = None
        try:
            buy_price = float(request.form.get("buy_price"))
            if buy_price <= 0:
                errors.append("Η τιμή αγοράς πρέπει να είναι θετική.")
        except (TypeError, ValueError):
            errors.append("Μη έγκυρη τιμή αγοράς.")
            buy_price = None
        if currency not in SUPPORTED_CURRENCIES:
            errors.append("Μη υποστηριζόμενο νόμισμα.")
        if not buy_date:
            errors.append("Η ημερομηνία αγοράς είναι υποχρεωτική.")

        if errors:
            db.close()
            for e in errors:
                flash(e, "danger")
            return render_template("edit.html", transaction=transaction, currencies=SUPPORTED_CURRENCIES)

        db.execute(
            """UPDATE transactions SET ticker = %s, shares = %s, buy_price = %s, currency = %s, buy_date = %
               WHERE id = %s AND user_id = %s""",
            (ticker, shares, buy_price, currency, buy_date, transaction_id, session["user_id"]),
        )
        db.commit()
        db.close()

        flash("Η συναλλαγή ενημερώθηκε.", "success")
        return redirect(url_for("index"))

    db.close()
    return render_template("edit.html", transaction=transaction, currencies=SUPPORTED_CURRENCIES)


@app.route("/delete/<int:transaction_id>", methods=["POST"])
@login_required
def delete(transaction_id):
    db = get_db()
    db.execute(
        "DELETE FROM transactions WHERE id = %s AND user_id = %s",
        (transaction_id, session["user_id"]),
    )
    db.commit()
    db.close()

    flash("Η συναλλαγή διαγράφηκε.", "success")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run()
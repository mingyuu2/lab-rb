import json
import socket
import time
from functools import wraps
from urllib.parse import unquote, urlparse

import requests
from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from db import close_db, get_db, init_db
from products import get_categories, get_product, get_products

app = Flask(__name__)
# Dev-only secret key: this is an intentionally isolated training lab, not
# internet-facing, so a hardcoded key is acceptable here.
app.secret_key = "dev-only-secret-key-for-training-lab"

app.teardown_appcontext(close_db)

SQUID_PROXIES = {
    "http": "http://proxy-server.internal:3128",
    "https": "http://proxy-server.internal:3128",
}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def _cart_items():
    cart = session.get("cart", {})
    items = []
    total = 0
    for pid, qty in cart.items():
        product = get_product(int(pid))
        if not product:
            continue
        subtotal = product["price"] * qty
        total += subtotal
        items.append({"product": product, "qty": qty, "subtotal": subtotal})
    return items, total


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        if not email or not password:
            error = "メールアドレスとパスワードを入力してください。"
        else:
            db = get_db()
            existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if existing:
                error = "すでに登録されているメールアドレスです。"
            else:
                db.execute(
                    "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                    (email, generate_password_hash(password)),
                )
                db.commit()
                return redirect(url_for("login"))
    return render_template("register.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["email"] = user["email"]
            return redirect(url_for("index"))
        error = "メールアドレスまたはパスワードが正しくありません。"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    category = request.args.get("category")
    return render_template(
        "index.html",
        products=get_products(category),
        categories=get_categories(),
        selected=category,
    )


@app.route("/product/<int:product_id>")
def product_detail(product_id):
    product = get_product(product_id)
    if not product:
        return "商品が見つかりません。", 404
    return render_template("product_detail.html", product=product)


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------


@app.route("/cart/add", methods=["POST"])
def cart_add():
    product_id = request.form.get("product_id")
    qty = int(request.form.get("qty", 1))
    cart = session.get("cart", {})
    cart[product_id] = cart.get(product_id, 0) + qty
    session["cart"] = cart
    return redirect(request.referrer or url_for("index"))


@app.route("/cart")
def cart_view():
    items, total = _cart_items()
    return render_template("cart.html", items=items, total=total)


@app.route("/cart/update", methods=["POST"])
def cart_update():
    product_id = request.form.get("product_id")
    qty = int(request.form.get("qty", 1))
    cart = session.get("cart", {})
    if qty <= 0:
        cart.pop(product_id, None)
    else:
        cart[product_id] = qty
    session["cart"] = cart
    return redirect(url_for("cart_view"))


@app.route("/cart/remove", methods=["POST"])
def cart_remove():
    product_id = request.form.get("product_id")
    cart = session.get("cart", {})
    cart.pop(product_id, None)
    session["cart"] = cart
    return redirect(url_for("cart_view"))


# ---------------------------------------------------------------------------
# Checkout (no real payment; form submit -> confirmation page only)
# ---------------------------------------------------------------------------


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    items, total = _cart_items()
    if not items:
        return redirect(url_for("cart_view"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        address = request.form.get("address", "").strip()
        session["cart"] = {}
        return render_template("order_complete.html", name=name, address=address)
    return render_template("checkout.html", items=items, total=total)


# ---------------------------------------------------------------------------
# Profile: normal feature, egress-compliant. Outbound fetches for the
# profile image go through Squid like company policy requires, and Squid's
# own Via header is passed through untouched -- just using this legitimate
# feature is enough for an attacker to learn the internal proxy hostname.
# ---------------------------------------------------------------------------


@app.route("/profile")
@login_required
def profile():
    return render_template("profile.html", image_url=session.get("profile_image_url"))


@app.route("/profile/image-preview", methods=["POST"])
@login_required
def profile_image_preview():
    url = request.form.get("url", "")
    if not url:
        return redirect(url_for("profile"))

    try:
        r = requests.get(url, allow_redirects=True, timeout=3, proxies=SQUID_PROXIES)
    except requests.exceptions.RequestException as e:
        return render_template("profile.html", image_url=None, error=str(e))

    session["profile_image_url"] = url
    # Squid genuinely adds Via for plain HTTP. For HTTPS it can only tunnel
    # the encrypted CONNECT stream -- it never sees the response to stamp --
    # so we add the equivalent header ourselves here to keep the leak from
    # being scheme-dependent.
    via = r.headers.get("Via") or "1.1 proxy-server.internal (squid/6.14)"
    body = render_template("profile.html", image_url=url)
    return Response(body, status=200, headers={"Via": via})


# ---------------------------------------------------------------------------
# Vulnerable path: product image auto-load fetches the destination directly,
# bypassing Squid entirely (an outbound-handling inconsistency vs. the
# profile feature above) -- no destination allowlist either. gopher:// is
# handled with a raw socket because `requests` has no gopher adapter.
# ---------------------------------------------------------------------------


@app.route("/product/image")
def product_image():
    url = request.args.get("url", "")
    if not url:
        return "url parameter required", 400

    parsed = urlparse(url)
    if parsed.scheme == "gopher":
        return _fetch_gopher(parsed)

    try:
        r = requests.get(url, allow_redirects=True, timeout=3)
    except requests.exceptions.Timeout:
        return Response("connection timeout", status=504)
    except requests.exceptions.ConnectionError as e:
        # A refused TCP connect (closed port) and a reset/bad-status-line
        # from an open-but-non-HTTP service (e.g. Redis) both surface here as
        # ConnectionError -- inspect the wrapped cause to tell them apart, so
        # blind port-scan practice still sees three distinct outcomes.
        if isinstance(e.args[0] if e.args else None, ConnectionRefusedError) or "Connection refused" in str(e):
            return Response(f"connection refused: {e}", status=502)
        return Response(f"port open, non-http response: {e}", status=200)
    except requests.exceptions.RequestException as e:
        return Response(f"error: {e}", status=502)

    return Response(
        r.content,
        status=200,
        content_type=r.headers.get("Content-Type", "application/octet-stream"),
    )


def _fetch_gopher(parsed):
    host = parsed.hostname
    port = parsed.port or 70
    raw_path = parsed.path.lstrip("/")
    if raw_path.startswith("_"):
        raw_path = raw_path[1:]
    payload = unquote(raw_path)

    try:
        with socket.create_connection((host, port), timeout=3) as s:
            s.sendall(payload.encode("latin-1", errors="replace"))
            s.settimeout(3)
            data = b""
            try:
                while True:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    data += chunk
            except socket.timeout:
                pass
        return Response(data, status=200, content_type="text/plain")
    except socket.timeout:
        return Response("connection timeout", status=504)
    except ConnectionRefusedError:
        return Response("connection refused", status=502)
    except OSError as e:
        return Response(f"error: {e}", status=502)


# ---------------------------------------------------------------------------
# 5. Result callback collection/lookup (unauthenticated by design)
# ---------------------------------------------------------------------------


@app.route("/internal/collect", methods=["POST"])
def internal_collect():
    payload = request.get_json(silent=True)
    if payload is None:
        if request.form:
            payload = dict(request.form)
        else:
            payload = request.get_data(as_text=True)
    if not isinstance(payload, str):
        payload = json.dumps(payload, ensure_ascii=False)

    db = get_db()
    db.execute(
        "INSERT INTO collected_results (source_ip, payload) VALUES (?, ?)",
        (request.remote_addr, payload),
    )
    db.commit()
    return "", 200


@app.route("/internal/results")
def internal_results():
    db = get_db()
    rows = db.execute("SELECT * FROM collected_results ORDER BY id DESC").fetchall()
    if request.args.get("format") == "json":
        return jsonify([dict(r) for r in rows])
    return render_template("internal_results.html", results=rows)


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80, threaded=True)

# Harvestline: Integration Guide

Flask 3 + Flask-SQLAlchemy (MySQL via PyMySQL) + Flask-Login + Flask-WTF (CSRF). Server-rendered Jinja, one small JS file.

## 1. Run it
```
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env        # set SECRET_KEY and DATABASE_URL
mysql -e "CREATE DATABASE agrimarket CHARACTER SET utf8mb4"
flask --app app init-db     # creates tables and seeds categories
flask --app app create-admin
gunicorn app:app            # serve behind HTTPS (cookies are Secure in production)
```

## 2. Layout
| File | Role |
|---|---|
| `app.py` | App factory, security headers, five blueprints: `shop`, `auth`, `buyer`, `farmer`, `admin` |
| `models.py` | Schema: User, FarmerProfile, Category, Product, CartItem, Address, Order, OrderItem, Dispute |
| `cart.py` | Dual-mode cart (session for guests, `cart_item` table for users) and `merge_guest_cart()` |
| `security.py` | `roles_required`, `save_image` (decode-verified uploads), `safe_next`, `clean` |
| `templates/_m.html` | Macros: `csrf()`, `card()`, `stamp()`, `badge()`, `track()` |
| `static/js/app.js` | Toasts, mobile nav, skeleton-to-image fade, AJAX add-to-cart |

Every child template starts with `{% extends 'base.html' %}{% import '_m.html' as m with context %}`. Macro imports are not inherited by child blocks in Jinja, and `with context` lets `track()` see `STATUSES`.

## 3. Guest cart and deferred sign-in
1. **Guest**: `session["cart"] = {"<product_id>": qty}`. `POST /cart/set` (fields `product_id`, `qty`, optional `mode=add`) clamps quantity to current stock.
2. **Read path**: `cart.lines()` returns `[(Product, qty)]` from the session or the DB depending on `current_user.is_authenticated`. `cart_count` is injected into every template by a context processor, so the navbar badge is always accurate.
3. **Gate**: `GET /checkout` with a non-empty cart and no login flashes a message and redirects to `/login?next=/checkout`. `next` is validated by `safe_next()` (relative paths only) to block open redirects.
4. **Merge**: after `login_user`, `auth._after_login()` calls `cart.merge_guest_cart()`. For each session item it adds to the account's `cart_item` row, **summing** quantities if the user already had that product and **capping at stock**, then clears `session["cart"]`. The user lands on `/checkout` with nothing lost.
5. **Register path**: `/register?next=/checkout` goes through the same `_after_login`. Farmers are redirected to onboarding instead, and their guest cart is not merged (only buyers can order).
6. **Order placement** (`POST /checkout`): locks product rows (`SELECT … FOR UPDATE`), verifies stock, decrements it, and creates **one Order per farmer** so each farmer fulfils only their items. Item titles and prices are copied onto `order_item`, so receipts stay accurate if a listing later changes.

## 4. View-to-backend map
| View | Route | Backend behaviour |
|---|---|---|
| `market.html` | `GET /market` | Filters: `q`, `cat`, `min`, `max`, `loc`, `fresh` (days), `sort`; only approved farms, active, unflagged, in-stock listings |
| `product.html` | `GET /product/<id>` | AJAX add-to-cart via `data-ajax` form; falls back to a normal POST |
| `cart.html` | `/cart`, `/cart/set` | Update or remove (qty 0) |
| `auth.html` | `/login`, `/register` | Shows "your N items will be waiting" when a guest cart exists |
| `buyer/*` | `/account/…` | Order tracking (`track` macro), receipts, cancel (Processing only, restores stock), disputes, addresses |
| `farmer/*` | `/farm/…` | Onboarding, listing CRUD (approved farms only), order status machine: Processing → Accepted → Shipped → Delivered; cancel allowed before shipping |
| `admin/*` | `/admin/…` | KPIs, verification queue (approve/reject with note), hide/restore listings, categories, dispute resolution |

Ownership is enforced server-side on every object route: wrong owner returns 404, wrong role returns 403.

## 5. Security controls
- **SQL injection**: SQLAlchemy ORM only; `LIKE` input has wildcards stripped. No string-built SQL.
- **CSRF**: `CSRFProtect` is global. Forms embed `{{ m.csrf() }}`; fetch calls send `X-CSRFToken` from the `<meta name="csrf-token">` tag. Logout is POST.
- **XSS**: Jinja autoescaping stays on (no `|safe` anywhere). CSP allows only same-origin scripts, no inline script or style, plus Google Fonts. Text inputs are whitespace-normalised and length-capped by `clean()`.
- **Cookies**: HttpOnly, SameSite=Lax, Secure in production, for both session and remember cookies.
- **Uploads**: 5 MB `MAX_CONTENT_LENGTH` (413 page), Pillow decodes the file to verify it is a real JPEG/PNG/WebP (extension and client MIME are ignored), pixel-count cap, image re-encoded and downsized, and stored under a random UUID name. The original filename is never used.
- **Auth**: hashed passwords (Werkzeug), 10+ character minimum, generic login error, role checks, deactivated users cannot sign in.
- **Headers**: `nosniff`, `X-Frame-Options: DENY`, referrer policy, CSP.

## 6. Not included yet (do before launch)
- **Payment gateway** (Paystack/Flutterwave): hook into `place_order`; today orders are pay-on-delivery.
- **Login rate limiting** (add Flask-Limiter on `/login`, `/register`), email verification, password reset.
- **Migrations** (Flask-Migrate) instead of `create_all`; automated tests.
- **Production uploads**: serve `static/uploads` from object storage/CDN.
- The smoke test was not run here (dependencies could not be installed in this sandbox), so run the flow once locally: browse, add to cart as guest, check out, register, confirm the cart survived.

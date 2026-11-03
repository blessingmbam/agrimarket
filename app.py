from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from flask import (Flask, Blueprint, render_template, request, redirect, url_for, flash,
                   session, jsonify, abort)
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import func
import re, cart as C
from config import Config
from models import *
from security import roles_required, save_image, safe_next, clean

csrf = CSRFProtect(); login_manager = LoginManager()
login_manager.login_view = "auth.login"; login_manager.login_message = "Sign in to continue."
STATUSES = ["Processing", "Accepted", "Shipped", "Delivered"]
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")

@login_manager.user_loader
def load_user(uid): return db.session.get(User, int(uid))

def create_app():
    app = Flask(__name__); app.config.from_object(Config)
    # app.config["TEMPLATES_AUTO_RELOAD"] = True; 
    db.init_app(app); csrf.init_app(app); login_manager.init_app(app)
    for bp in (shop, auth, buyer, farmer, admin): app.register_blueprint(bp)
    @app.context_processor
    def inject(): return dict(cart_count=C.count(), STATUSES=STATUSES)
    @app.after_request
    def headers(r):
        r.headers["X-Content-Type-Options"] = "nosniff"; r.headers["X-Frame-Options"] = "DENY"
        r.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        r.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data:; "
            "style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
            "script-src 'self'; frame-ancestors 'none'; form-action 'self'")
        return r
    for code, msg in ((403, "You don't have access to this page."), (404, "We couldn't find that page."),
                      (413, "That file is over the 5 MB limit.")):
        app.register_error_handler(code, lambda e, c=code, m=msg: (render_template("error.html", code=c, msg=m), c))
    @app.cli.command("init-db")
    def init_db():
        db.create_all()
        for n, k in [("Vegetables","crop"),("Fruit","crop"),("Grains","crop"),("Poultry","livestock"),("Goats & sheep","livestock"),("Milk & cheese","dairy"),("Eggs","dairy")]:
            if not Category.query.filter_by(name=n).first(): db.session.add(Category(name=n, kind=k))
        db.session.commit(); print("Database ready.")
    @app.cli.command("create-admin")
    def create_admin():
        import getpass
        e = input("Admin email: ").strip().lower(); u = User(email=e, name="Administrator", role="admin")
        u.set_password(getpass.getpass("Password (12+ chars): ")); db.session.add(u); db.session.commit()
    return app

# ---------- helpers
def money(v, default=None):
    try:
        d = Decimal(v).quantize(Decimal("0.01"))
        return d if d >= 0 else default
    except (InvalidOperation, TypeError): return default
def to_int(v, default=0, lo=0, hi=10**6):
    try: return max(lo, min(int(v), hi))
    except (TypeError, ValueError): return default

# ---------- public marketplace + guest cart
shop = Blueprint("shop", __name__)
@shop.get("/")
def index():
    feats = Product.query.filter_by(is_active=True, is_flagged=False).order_by(Product.created.desc()).limit(8).all()
    return render_template("index.html", feats=feats, cats=Category.query.all())

@shop.get("/market")
def market():
    q = Product.query.join(User, Product.farmer_id == User.id).join(FarmerProfile, FarmerProfile.user_id == User.id)\
        .filter(Product.is_active.is_(True), Product.is_flagged.is_(False), Product.stock > 0, FarmerProfile.status == "approved")
    s = clean(request.args.get("q"), 80); cat = to_int(request.args.get("cat"), 0)
    lo = money(request.args.get("min")); hi = money(request.args.get("max")); loc = clean(request.args.get("loc"), 80)
    fresh = to_int(request.args.get("fresh"), 0, 0, 365); sort = request.args.get("sort", "new")
    if s: q = q.filter(Product.title.ilike(f"%{s.replace('%','').replace('_','')}%"))
    if cat: q = q.filter(Product.category_id == cat)
    if lo is not None: q = q.filter(Product.price >= lo)
    if hi is not None: q = q.filter(Product.price <= hi)
    if loc: q = q.filter(Product.location.ilike(f"%{loc.replace('%','')}%"))
    if fresh: q = q.filter(Product.harvest_date >= date.fromordinal(date.today().toordinal() - fresh))
    q = q.order_by({"low": Product.price.asc(), "high": Product.price.desc(), "fresh": Product.harvest_date.desc()}.get(sort, Product.created.desc()))
    page = q.paginate(page=to_int(request.args.get("page"), 1, 1), per_page=12, error_out=False)
    
    # Filter out 'page' from request.args for pagination links
    filtered_args = {k: v for k, v in request.args.items() if k != 'page'}
    
    return render_template("market.html", page=page, cats=Category.query.all(), filtered_args=filtered_args)

@shop.get("/product/<int:pid>")
def product(pid):
    p = db.get_or_404(Product, pid)
    if not p.is_active and not (current_user.is_authenticated and current_user.id in (p.farmer_id,) or (current_user.is_authenticated and current_user.role == "admin")): abort(404)
    return render_template("product.html", p=p, in_cart=C.get_qty(pid))

@shop.get("/cart")
def cart_view():
    return render_template("cart.html", lines=C.lines(), total=C.total())

@shop.post("/cart/set")
def cart_set():
    pid, qty = to_int(request.form.get("product_id")), to_int(request.form.get("qty"), 0, 0, 999)
    if request.form.get("mode") == "add": qty = C.get_qty(pid) + max(qty, 1)
    ok = C.set_qty(pid, qty)
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(ok=ok, count=C.count(), total=str(C.total()), msg="Cart updated" if ok else "Item unavailable")
    flash("Cart updated." if ok else "That item is no longer available.", "success" if ok else "error")
    return redirect(request.referrer if request.referrer and request.host in request.referrer else url_for("shop.cart_view"))

@shop.get("/checkout")
def checkout():
    if not C.lines():
        flash("Your cart is empty.", "info"); return redirect(url_for("shop.market"))
    if not current_user.is_authenticated:   # lazy auth gate
        flash("Sign in or create an account to finish your order. Your cart is saved.", "info")
        return redirect(url_for("auth.login", next=url_for("shop.checkout")))
    if current_user.role != "buyer":
        flash("Use a buyer account to place orders.", "error"); return redirect(url_for("shop.cart_view"))
    return render_template("checkout.html", lines=C.lines(), total=C.total(),
                           addresses=Address.query.filter_by(user_id=current_user.id).all())

@shop.post("/checkout")
@roles_required("buyer")
def place_order():
    addr = db.session.get(Address, to_int(request.form.get("address_id")))
    if not addr or addr.user_id != current_user.id:
        flash("Choose a delivery address.", "error"); return redirect(url_for("shop.checkout"))
    by_farmer = {}
    try:
        for ci in CartItem.query.filter_by(user_id=current_user.id).all():
            p = db.session.query(Product).filter_by(id=ci.product_id).with_for_update().first()  # row lock
            if not p.is_active or p.stock < ci.qty: raise ValueError(f"“{p.title}” has only {p.stock} left.")
            p.stock -= ci.qty; by_farmer.setdefault(p.farmer_id, []).append((p, ci))
        if not by_farmer: raise ValueError("Your cart is empty.")
        ship = f"{addr.line1}, {addr.city}{', ' + addr.state if addr.state else ''} · {addr.phone or current_user.phone or ''}"
        for fid, rows in by_farmer.items():
            o = Order(buyer_id=current_user.id, farmer_id=fid, ship_to=ship, total=sum(p.price * c.qty for p, c in rows))
            o.items = [OrderItem(product_id=p.id, title=p.title, unit=p.unit, price=p.price, qty=c.qty) for p, c in rows]
            db.session.add(o)
        CartItem.query.filter_by(user_id=current_user.id).delete()
        db.session.commit()
    except ValueError as e:
        db.session.rollback(); flash(str(e), "error"); return redirect(url_for("shop.cart_view"))
    flash("Order placed. Farmers have been notified.", "success"); return redirect(url_for("buyer.orders"))

# ---------- auth
auth = Blueprint("auth", __name__)
def _after_login(user):
    login_user(user, remember=True); session.permanent = True
    if user.role == "buyer": C.merge_guest_cart()
    flash(f"Welcome, {user.name.split()[0]}.", "success")
    nxt = safe_next(request.values.get("next"))
    return redirect(nxt or {"buyer": url_for("buyer.dashboard"), "farmer": url_for("farmer.dashboard"), "admin": url_for("admin.dashboard")}[user.role])

@auth.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = User.query.filter_by(email=clean(request.form.get("email"), 190).lower()).first()
        if u and u.is_active and u.check_password(request.form.get("password", "")): return _after_login(u)
        flash("Email or password is incorrect.", "error")
    return render_template("auth.html", mode="login", next=safe_next(request.values.get("next")))

@auth.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        f = request.form; email = clean(f.get("email"), 190).lower(); name = clean(f.get("name"), 120)
        role = "farmer" if f.get("role") == "farmer" else "buyer"; pw = f.get("password", "")
        err = (not EMAIL.match(email) and "Enter a valid email.") or (len(name) < 2 and "Enter your name.") \
            or (len(pw) < 10 and "Use a password of 10+ characters.") or (User.query.filter_by(email=email).first() and "That email already has an account.")
        if err: flash(err, "error")
        else:
            u = User(email=email, name=name, phone=clean(f.get("phone"), 30), role=role); u.set_password(pw)
            db.session.add(u); db.session.commit()
            if role == "farmer": login_user(u); flash("Account created. Complete your farm profile.", "success"); return redirect(url_for("farmer.onboarding"))
            return _after_login(u)
    return render_template("auth.html", mode="register", next=safe_next(request.values.get("next")))

@auth.post("/logout")
def logout(): logout_user(); flash("Signed out.", "info"); return redirect(url_for("shop.index"))

# ---------- buyer
buyer = Blueprint("buyer", __name__, url_prefix="/account")
@buyer.get("/")
@roles_required("buyer")
def dashboard():
    active = Order.query.filter(Order.buyer_id == current_user.id, Order.status.in_(STATUSES[:3])).order_by(Order.created.desc()).all()
    return render_template("buyer/dashboard.html", active=active)
@buyer.get("/orders")
@roles_required("buyer")
def orders():
    return render_template("buyer/orders.html", orders=Order.query.filter_by(buyer_id=current_user.id).order_by(Order.created.desc()).all())
@buyer.get("/orders/<int:oid>")
@roles_required("buyer")
def invoice(oid):
    o = db.get_or_404(Order, oid)
    if o.buyer_id != current_user.id: abort(404)
    return render_template("buyer/invoice.html", o=o)
@buyer.post("/orders/<int:oid>/cancel")
@roles_required("buyer")
def cancel(oid):
    o = db.get_or_404(Order, oid)
    if o.buyer_id != current_user.id: abort(404)
    if o.status != "Processing": flash("Only orders not yet accepted can be canceled.", "error")
    else:
        for i in o.items:
            p = db.session.get(Product, i.product_id)
            if p: p.stock += i.qty
        o.status = "Canceled"; db.session.commit(); flash("Order canceled.", "success")
    return redirect(url_for("buyer.orders"))
@buyer.post("/orders/<int:oid>/dispute")
@roles_required("buyer")
def dispute(oid):
    o = db.get_or_404(Order, oid)
    if o.buyer_id != current_user.id: abort(404)
    r = clean(request.form.get("reason"), 1000)
    if len(r) < 10: flash("Describe the problem in a sentence or two.", "error")
    else: db.session.add(Dispute(order_id=o.id, opened_by=current_user.id, reason=r)); db.session.commit(); flash("Dispute sent to our team.", "success")
    return redirect(url_for("buyer.invoice", oid=oid))

@buyer.route("/disputes/new", methods=["GET", "POST"])
@roles_required("buyer")
def new_dispute():
    user_orders = Order.query.filter_by(buyer_id=current_user.id).order_by(Order.created.desc()).all()
    
    if request.method == "POST":
        order_id = to_int(request.form.get("order_id"))
        reason = clean(request.form.get("reason"), 1000)
        
        # Verify order belongs to the current user
        order = db.session.get(Order, order_id)
        if not order or order.buyer_id != current_user.id:
            flash("Please select a valid order.", "error")
            return redirect(url_for("buyer.new_dispute"))
            
        if len(reason) < 10:
            flash("Describe the problem in a sentence or two (at least 10 characters).", "error")
        else:
            # Save the dispute to the database
            db.session.add(Dispute(order_id=order.id, opened_by=current_user.id, reason=reason))
            db.session.commit()
            flash("Dispute sent to our team.", "success")
            return redirect(url_for("buyer.orders"))
            
    return render_template("buyer/dispute_form.html", orders=user_orders)
@buyer.route("/profile", methods=["GET", "POST"])
@roles_required("buyer")
def profile():
    if request.method == "POST":
        a = request.form.get("action")
        if a == "profile": current_user.name = clean(request.form.get("name"), 120) or current_user.name; current_user.phone = clean(request.form.get("phone"), 30)
        elif a == "address" and clean(request.form.get("line1")) and clean(request.form.get("city")):
            db.session.add(Address(user_id=current_user.id, label=clean(request.form.get("label"), 40), line1=clean(request.form.get("line1")),
                                   city=clean(request.form.get("city"), 80), state=clean(request.form.get("state"), 80), phone=clean(request.form.get("phone"), 30)))
        elif a == "del":
            ad = db.session.get(Address, to_int(request.form.get("id")))
            if ad and ad.user_id == current_user.id: db.session.delete(ad)
        db.session.commit(); flash("Saved.", "success"); return redirect(url_for("buyer.profile"))
    return render_template("buyer/profile.html", addresses=Address.query.filter_by(user_id=current_user.id).all())

# ---------- farmer
farmer = Blueprint("farmer", __name__, url_prefix="/farm")
def approved_farmer():
    return current_user.farm and current_user.farm.status == "approved"
@farmer.route("/onboarding", methods=["GET", "POST"])
@roles_required("farmer")
def onboarding():
    fp = current_user.farm
    if request.method == "POST":
        fn, lc = clean(request.form.get("farm_name"), 150), clean(request.form.get("location"), 150)
        if not fn or not lc: flash("Farm name and location are required.", "error")
        else:
            fp = fp or FarmerProfile(user_id=current_user.id); fp.farm_name, fp.location = fn, lc
            fp.bio = clean(request.form.get("bio"), 1500); fp.credentials = clean(request.form.get("credentials"), 1500)
            if fp.status == "rejected": fp.status = "pending"
            db.session.add(fp); db.session.commit(); flash("Profile submitted for verification.", "success"); return redirect(url_for("farmer.dashboard"))
    return render_template("farmer/onboarding.html", fp=fp)
@farmer.get("/")
@roles_required("farmer")
def dashboard():
    if not current_user.farm: return redirect(url_for("farmer.onboarding"))
    ps = Product.query.filter_by(farmer_id=current_user.id).order_by(Product.created.desc()).all()
    pend = Order.query.filter_by(farmer_id=current_user.id, status="Processing").count()
    rev = db.session.query(func.coalesce(func.sum(Order.total), 0)).filter(Order.farmer_id == current_user.id, Order.status == "Delivered").scalar()
    return render_template("farmer/dashboard.html", ps=ps, pend=pend, rev=rev)
def _product_form(p=None):
    f = request.form; err = None
    title = clean(f.get("title"), 150); price = money(f.get("price")); cat = db.session.get(Category, to_int(f.get("category_id")))
    try: hd = datetime.strptime(f.get("harvest_date", ""), "%Y-%m-%d").date()
    except ValueError: hd = None
    if not title or price is None or not cat or hd is None or hd > date.today(): return "Check title, category, price and a harvest date that isn't in the future."
    try: img = save_image(request.files.get("image"))
    except ValueError as e: return str(e)
    p = p or Product(farmer_id=current_user.id)
    p.title, p.price, p.category_id, p.harvest_date = title, price, cat.id, hd
    p.description = clean(f.get("description"), 3000); p.unit = clean(f.get("unit"), 20) or "kg"
    p.stock = to_int(f.get("stock"), 0, 0, 10**6); p.location = clean(f.get("location"), 150) or current_user.farm.location
    p.is_active = bool(f.get("is_active"))
    if img: p.image = img
    db.session.add(p); db.session.commit()
@farmer.route("/products/new", methods=["GET", "POST"])
@farmer.route("/products/<int:pid>/edit", methods=["GET", "POST"])
@roles_required("farmer")
def product_form(pid=None):
    if not approved_farmer(): flash("Listings unlock once your farm is verified.", "info"); return redirect(url_for("farmer.dashboard"))
    p = db.get_or_404(Product, pid) if pid else None
    if p and p.farmer_id != current_user.id: abort(404)
    if request.method == "POST":
        err = _product_form(p)
        if err: flash(err, "error")
        else: flash("Listing saved.", "success"); return redirect(url_for("farmer.dashboard"))
    return render_template("farmer/product_form.html", p=p, cats=Category.query.all(), today=date.today().isoformat())
@farmer.post("/products/<int:pid>/delete")
@roles_required("farmer")
def product_delete(pid):
    p = db.get_or_404(Product, pid)
    if p.farmer_id != current_user.id: abort(404)
    if OrderItem.query.filter_by(product_id=pid).first(): p.is_active = False; flash("Listing hidden (it has past orders).", "info")
    else: CartItem.query.filter_by(product_id=pid).delete(); db.session.delete(p); flash("Listing deleted.", "success")
    db.session.commit(); return redirect(url_for("farmer.dashboard"))
@farmer.get("/orders")
@roles_required("farmer")
def orders():
    return render_template("farmer/orders.html", orders=Order.query.filter_by(farmer_id=current_user.id).order_by(Order.created.desc()).all())
@farmer.post("/orders/<int:oid>/status")
@roles_required("farmer")
def order_status(oid):
    o = db.get_or_404(Order, oid)
    if o.farmer_id != current_user.id: abort(404)
    nxt = request.form.get("status")
    allowed = {"Processing": ["Accepted", "Canceled"], "Accepted": ["Shipped", "Canceled"], "Shipped": ["Delivered"]}
    if nxt in allowed.get(o.status, []):
        if nxt == "Canceled":
            for i in o.items:
                p = db.session.get(Product, i.product_id)
                if p: p.stock += i.qty
        o.status = nxt; db.session.commit(); flash(f"Order #{o.id} marked {nxt.lower()}.", "success")
    else: flash("That status change isn't allowed.", "error")
    return redirect(url_for("farmer.orders"))

# ---------- admin
admin = Blueprint("admin", __name__, url_prefix="/admin")
@admin.get("/")
@roles_required("admin")
def dashboard():
    s = dict(volume=db.session.query(func.coalesce(func.sum(Order.total), 0)).filter(Order.status != "Canceled").scalar(),
             farmers=FarmerProfile.query.filter_by(status="approved").count(), pending_orders=Order.query.filter_by(status="Processing").count(),
             queue=FarmerProfile.query.filter_by(status="pending").count(), disputes=Dispute.query.filter_by(status="open").count(), buyers=User.query.filter_by(role="buyer").count())
    return render_template("admin/dashboard.html", s=s, recent=Order.query.order_by(Order.created.desc()).limit(8).all())
@admin.get("/farmers")
@roles_required("admin")
def farmers(): return render_template("admin/farmers.html", fps=FarmerProfile.query.order_by(FarmerProfile.status.desc()).all())
@admin.post("/farmers/<int:fid>")
@roles_required("admin")
def farmer_decide(fid):
    fp = db.get_or_404(FarmerProfile, fid); d = request.form.get("decision")
    if d in ("approved", "rejected"): fp.status = d; fp.admin_note = clean(request.form.get("note"), 255); db.session.commit(); flash(f"Farm {d}.", "success")
    return redirect(url_for("admin.farmers"))
@admin.route("/moderation", methods=["GET", "POST"])
@roles_required("admin")
def moderation():
    if request.method == "POST":
        p = db.get_or_404(Product, to_int(request.form.get("id"))); p.is_flagged = request.form.get("action") == "hide"; db.session.commit()
        flash("Listing hidden." if p.is_flagged else "Listing restored.", "success"); return redirect(url_for("admin.moderation"))
    return render_template("admin/moderation.html", ps=Product.query.order_by(Product.is_flagged.desc(), Product.created.desc()).limit(100).all())
@admin.route("/categories", methods=["GET", "POST"])
@roles_required("admin")
def categories():
    if request.method == "POST":
        a = request.form.get("action"); name = clean(request.form.get("name"), 80)
        if a == "add" and name and not Category.query.filter_by(name=name).first():
            db.session.add(Category(name=name, kind=request.form.get("kind") if request.form.get("kind") in ("crop","livestock","dairy","other") else "other"))
        elif a == "del":
            c = db.session.get(Category, to_int(request.form.get("id")))
            if c and not Product.query.filter_by(category_id=c.id).first(): db.session.delete(c)
            else: flash("Move or remove its listings first.", "error")
        db.session.commit(); return redirect(url_for("admin.categories"))
    return render_template("admin/categories.html", cats=Category.query.all())
@admin.route("/disputes", methods=["GET", "POST"])
@roles_required("admin")
def disputes():
    if request.method == "POST":
        d = db.get_or_404(Dispute, to_int(request.form.get("id"))); d.status = "resolved"; d.resolution = clean(request.form.get("resolution"), 1000)
        db.session.commit(); flash("Dispute resolved.", "success"); return redirect(url_for("admin.disputes"))
    return render_template("admin/disputes.html", ds=Dispute.query.order_by(Dispute.status.desc(), Dispute.created.desc()).all())

app = create_app()
if __name__ == "__main__": app.run(debug=False)

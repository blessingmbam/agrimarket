from decimal import Decimal
from flask import session
from flask_login import current_user
from models import db, CartItem, Product
def _sess(): return session.setdefault("cart", {})
def lines():
    """Unified view: DB cart if signed in, session cart otherwise -> [(product, qty)]"""
    if current_user.is_authenticated:
        rows = CartItem.query.filter_by(user_id=current_user.id).all()
        return [(r.product, r.qty) for r in rows if r.product and r.product.is_active]
    ids = [int(i) for i in _sess()]
    ps = {p.id: p for p in Product.query.filter(Product.id.in_(ids), Product.is_active.is_(True)).all()} if ids else {}
    return [(ps[i], q) for i, q in ((int(k), v) for k, v in _sess().items()) if i in ps]
def count(): return sum(q for _, q in lines())
def total(): return sum((p.price * q for p, q in lines()), Decimal("0"))
def set_qty(pid, qty):
    p = db.session.get(Product, pid)
    if not p or not p.is_active: return False
    qty = max(0, min(qty, p.stock))
    if current_user.is_authenticated:
        row = CartItem.query.filter_by(user_id=current_user.id, product_id=pid).first()
        if qty == 0 and row: db.session.delete(row)
        elif row: row.qty = qty
        elif qty: db.session.add(CartItem(user_id=current_user.id, product_id=pid, qty=qty))
        db.session.commit()
    else:
        c = _sess()
        if qty: c[str(pid)] = qty
        else: c.pop(str(pid), None)
        session.modified = True
    return True
def get_qty(pid):
    return dict((p.id, q) for p, q in lines()).get(pid, 0)
def merge_guest_cart():
    """Called right after login/registration: fold session cart into the account cart."""
    guest = session.pop("cart", {})
    for k, q in guest.items():
        p = db.session.get(Product, int(k))
        if not p or not p.is_active: continue
        row = CartItem.query.filter_by(user_id=current_user.id, product_id=p.id).first()
        newq = min((row.qty if row else 0) + int(q), p.stock)  # sum, capped at stock
        if row: row.qty = newq
        elif newq > 0: db.session.add(CartItem(user_id=current_user.id, product_id=p.id, qty=newq))
    db.session.commit()

from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(190), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30))
    pw_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum("buyer", "farmer", "admin"), default="buyer", nullable=False)
    is_active_flag = db.Column(db.Boolean, default=True)
    created = db.Column(db.DateTime, default=datetime.utcnow)
    farm = db.relationship("FarmerProfile", backref="user", uselist=False)
    def set_password(self, p): self.pw_hash = generate_password_hash(p)
    def check_password(self, p): return check_password_hash(self.pw_hash, p)
    @property
    def is_active(self): return self.is_active_flag

class FarmerProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True)
    farm_name = db.Column(db.String(150), nullable=False)
    location = db.Column(db.String(150), nullable=False)
    bio = db.Column(db.Text)
    credentials = db.Column(db.Text)  # registration no., certifications
    status = db.Column(db.Enum("pending", "approved", "rejected"), default="pending", index=True)
    admin_note = db.Column(db.String(255))

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    kind = db.Column(db.Enum("crop", "livestock", "dairy", "other"), default="crop")

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    farmer_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), index=True, nullable=False)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    unit = db.Column(db.String(20), default="kg")
    price = db.Column(db.Numeric(10, 2), nullable=False)
    stock = db.Column(db.Integer, default=0, nullable=False)
    harvest_date = db.Column(db.Date, default=date.today, index=True)
    location = db.Column(db.String(150))
    image = db.Column(db.String(80))
    is_active = db.Column(db.Boolean, default=True)
    is_flagged = db.Column(db.Boolean, default=False)
    created = db.Column(db.DateTime, default=datetime.utcnow)
    farmer = db.relationship("User"); category = db.relationship("Category")
    @property
    def freshness_days(self): return (date.today() - self.harvest_date).days if self.harvest_date else 999

class CartItem(db.Model):
    __table_args__ = (db.UniqueConstraint("user_id", "product_id"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"))
    qty = db.Column(db.Integer, default=1)
    product = db.relationship("Product")

class Address(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
    label = db.Column(db.String(40)); line1 = db.Column(db.String(200), nullable=False)
    city = db.Column(db.String(80), nullable=False); state = db.Column(db.String(80))
    phone = db.Column(db.String(30))

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
    farmer_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
    status = db.Column(db.Enum("Processing", "Accepted", "Shipped", "Delivered", "Canceled"), default="Processing", index=True)
    total = db.Column(db.Numeric(12, 2), nullable=False)
    ship_to = db.Column(db.String(400), nullable=False)
    created = db.Column(db.DateTime, default=datetime.utcnow)
    buyer = db.relationship("User", foreign_keys=[buyer_id]); farmer = db.relationship("User", foreign_keys=[farmer_id])
    items = db.relationship("OrderItem", backref="order", cascade="all, delete-orphan")

class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"))
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"))
    title = db.Column(db.String(150)); unit = db.Column(db.String(20))
    price = db.Column(db.Numeric(10, 2)); qty = db.Column(db.Integer)

class Dispute(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"))
    opened_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.Enum("open", "resolved"), default="open")
    resolution = db.Column(db.Text)
    created = db.Column(db.DateTime, default=datetime.utcnow)
    order = db.relationship("Order")

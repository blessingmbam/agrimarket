import os, uuid, re
from functools import wraps
from flask import abort, current_app, redirect, url_for, flash, request
from flask_login import current_user
from PIL import Image
ALLOWED = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
def roles_required(*roles):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login", next=request.path))
            if current_user.role not in roles: abort(403)
            return f(*a, **k)
        return w
    return deco
def save_image(fs):
    """Verify by decoding (not by extension/Content-Type); re-encode; random name."""
    if not fs or not fs.filename: return None
    try:
        img = Image.open(fs.stream); fmt = img.format; img.verify()
        fs.stream.seek(0); img = Image.open(fs.stream)
    except Exception:
        raise ValueError("Upload a valid JPG, PNG or WebP image.")
    if fmt not in ALLOWED: raise ValueError("Only JPG, PNG or WebP images are accepted.")
    if img.width * img.height > 40_000_000: raise ValueError("Image dimensions are too large.")
    img.thumbnail((1600, 1600))
    name = f"{uuid.uuid4().hex}.{ALLOWED[fmt]}"
    os.makedirs(current_app.config["UPLOAD_DIR"], exist_ok=True)
    img.convert("RGB" if fmt == "JPEG" else img.mode).save(os.path.join(current_app.config["UPLOAD_DIR"], name), fmt, quality=85)
    return name
def safe_next(target):
    return target if target and re.fullmatch(r"/[A-Za-z0-9_\-./?=&%]*", target) and not target.startswith("//") else None
def clean(s, n=200): return " ".join((s or "").split())[:n]

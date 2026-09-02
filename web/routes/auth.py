from flask import Blueprint, render_template, request, redirect, url_for, session
from scripts.accounts.auth import authenticate, register_user

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if password != confirm_password:
            return render_template("register.html", error="Passwords do not match."), 400
        user_id, error = register_user(request.form.get("username", ""), request.form.get("email", ""), password)
        if error:
            return render_template("register.html", error=error), 400
        session.clear()
        session["user_id"] = user_id
        return redirect(url_for("stats.home"))
    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = authenticate(request.form.get("login", ""), request.form.get("password", ""))
        if not user:
            return render_template("login.html", error="Invalid username/email or password."), 401
        session.clear()
        session["user_id"] = user["id"]
        return redirect(url_for("stats.home"))
    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("stats.home"))

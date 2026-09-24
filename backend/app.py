import os
from functools import wraps

import psycopg2
from flask import Flask, redirect, render_template, request, session, url_for
from psycopg2.extras import RealDictCursor

from rules import joint_mean, weigh

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "tea-cupping-dev-secret")

ACCOUNTS = {
    "taster": {"password": "tea123456", "role": "writer"},
    "observer": {"password": "look123456", "role": "reader"},
}


def db():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def login_required(fn):
    @wraps(fn)
    def wrap(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)

    return wrap


def writer_required(fn):
    @wraps(fn)
    def wrap(*args, **kwargs):
        if session.get("role") != "writer":
            return ("仅审评员可进入联评台", 403)
        return fn(*args, **kwargs)

    return wrap


def read_scores(form):
    try:
        return (
            float(form["aroma"]),
            float(form["taste"]),
            float(form["liquor"]),
        )
    except (KeyError, ValueError):
        return None


@app.get("/health")
def health():
    return {"status": "ok", "service": "tea-blend-cupping"}


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        name = request.form.get("username", "").strip()
        account = ACCOUNTS.get(name)
        if not account or account["password"] != request.form.get("password", ""):
            error = "用户名或密码错误"
        else:
            session["user"] = name
            session["role"] = account["role"]
            return redirect(url_for("home"))
    return render_template("login.html", error=error)


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
@login_required
def home():
    with db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM cuppings ORDER BY id DESC")
        rows = cur.fetchall()
    return render_template("home.html", rows=rows)


@app.get("/joint")
@login_required
@writer_required
def joint():
    with db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM joint_drafts WHERE status = 'pending' ORDER BY id DESC"
        )
        pending = cur.fetchall()
        cur.execute(
            """SELECT d.id AS draft_id, d.lot, d.created_by,
                      c.aroma, c.taste, c.liquor, c.score, c.verdict, c.note
               FROM joint_drafts d
               JOIN cuppings c ON c.id = d.cupping_id
               WHERE d.status = 'synthesized'
               ORDER BY d.id DESC"""
        )
        done = cur.fetchall()
    return render_template("joint.html", pending=pending, done=done)


@app.post("/joint/drafts")
@login_required
@writer_required
def create_draft():
    lot = request.form.get("lot", "").strip()
    scores = read_scores(request.form)
    if not lot or scores is None:
        return ("批次与三项评分必填", 400)
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO joint_drafts (lot, aroma, taste, liquor, created_by)
               VALUES (%s,%s,%s,%s,%s)""",
            (lot, *scores, session["user"]),
        )
        conn.commit()
    return redirect(url_for("joint"))


@app.post("/joint/complete")
@login_required
@writer_required
def complete_draft():
    try:
        draft_id = int(request.form["draft_id"])
    except (KeyError, ValueError):
        return ("草稿号无效", 400)
    scores = read_scores(request.form)
    if scores is None:
        return ("三项评分必填", 400)
    aroma, taste, liquor = scores
    with db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM joint_drafts WHERE id = %s FOR UPDATE", (draft_id,)
        )
        draft = cur.fetchone()
        if draft is None:
            return ("草稿号不存在", 404)
        if draft["status"] != "pending":
            return ("该草稿已合成，不能重复交齐", 409)
        avg_aroma = joint_mean(draft["aroma"], aroma)
        avg_taste = joint_mean(draft["taste"], taste)
        avg_liquor = joint_mean(draft["liquor"], liquor)
        verdict, note, score = weigh(avg_aroma, avg_taste, avg_liquor)
        cur.execute(
            """INSERT INTO cuppings (lot, aroma, taste, liquor, score, verdict, note, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (
                draft["lot"],
                avg_aroma,
                avg_taste,
                avg_liquor,
                score,
                verdict,
                note,
                session["user"],
            ),
        )
        cupping_id = cur.fetchone()["id"]
        cur.execute(
            "UPDATE joint_drafts SET status = 'synthesized', cupping_id = %s WHERE id = %s",
            (cupping_id, draft_id),
        )
        conn.commit()
    return redirect(url_for("joint"))

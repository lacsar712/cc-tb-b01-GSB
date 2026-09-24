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
    "taster2": {"password": "tea234567", "role": "writer"},
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
        if "user" not in session:
            return redirect(url_for("login"))
        if session.get("role") != "writer":
            return ("仅审评员可进入联评台", 403)
        return fn(*args, **kwargs)

    return wrap


def read_scores(form):
    return (
        float(form["aroma"]),
        float(form["taste"]),
        float(form["liquor"]),
    )


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
    return render_template("home.html", rows=rows, can_write=session.get("role") == "writer")


@app.get("/joint")
@writer_required
def joint():
    with db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """SELECT * FROM joint_drafts
               WHERE cupping_id IS NULL ORDER BY created_at DESC"""
        )
        pending = cur.fetchall()
        cur.execute(
            """SELECT d.*, c.lot AS c_lot, c.aroma AS c_aroma, c.taste AS c_taste,
                      c.liquor AS c_liquor, c.score AS c_score, c.verdict AS c_verdict
               FROM joint_drafts d JOIN cuppings c ON c.id = d.cupping_id
               ORDER BY d.cupping_id DESC"""
        )
        done = cur.fetchall()
    return render_template("joint.html", pending=pending, done=done)


@app.post("/joint/drafts")
@writer_required
def create_draft():
    lot = request.form.get("lot", "").strip()
    if not lot:
        return ("批次不能为空", 400)
    aroma, taste, liquor = read_scores(request.form)
    with db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT nextval('joint_draft_seq')")
        draft_no = f"D-{int(cur.fetchone()['nextval']):04d}"
        cur.execute(
            """INSERT INTO joint_drafts
                   (draft_no, lot, aroma_a, taste_a, liquor_a, taster_a)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (draft_no, lot, aroma, taste, liquor, session["user"]),
        )
        conn.commit()
    return redirect(url_for("joint") + f"?draft={draft_no}")


@app.post("/joint/synthesize")
@writer_required
def synthesize():
    draft_no = request.form.get("draft_no", "").strip()
    aroma, taste, liquor = read_scores(request.form)
    with db() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM joint_drafts WHERE draft_no = %s FOR UPDATE", (draft_no,))
        draft = cur.fetchone()
        if draft is None:
            return (f"草稿号 {draft_no} 不存在，联评未合成", 400)
        if draft["cupping_id"] is not None:
            return (f"草稿号 {draft_no} 已合成，不能重复交齐", 400)
        if draft["taster_a"] == session["user"]:
            return ("联评须由另一名审评员引用草稿交齐", 400)

        m_aroma = joint_mean(draft["aroma_a"], aroma)
        m_taste = joint_mean(draft["taste_a"], taste)
        m_liquor = joint_mean(draft["liquor_a"], liquor)
        verdict, note, score = weigh(m_aroma, m_taste, m_liquor)
        cur.execute(
            """INSERT INTO cuppings (lot, aroma, taste, liquor, score, verdict, note, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (
                draft["lot"], m_aroma, m_taste, m_liquor, score, verdict,
                f"联评合成（{draft['taster_a']} 与 {session['user']} 均值）：{note}",
                f"{draft['taster_a']}+{session['user']}",
            ),
        )
        cupping_id = cur.fetchone()["id"]
        cur.execute(
            """UPDATE joint_drafts
               SET aroma_b=%s, taste_b=%s, liquor_b=%s, taster_b=%s, cupping_id=%s
               WHERE draft_no=%s""",
            (aroma, taste, liquor, session["user"], cupping_id, draft_no),
        )
        conn.commit()
    return redirect(url_for("joint"))

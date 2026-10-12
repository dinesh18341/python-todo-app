import os
import re
import sqlite3
import time
from datetime import datetime, date, timedelta, timezone
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   session, g)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
# On Render we will set a real SECRET_KEY. This default is only for your own computer.
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  PERMANENT_SESSION_LIFETIME=timedelta(days=30))

# India time (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "todo.db"))

PALETTE = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ec4899",
           "#8b5cf6", "#14b8a6", "#f97316", "#84cc16", "#64748b"]

CATEGORIES = {
    "Study":    {"icon": "📚", "color": "#60a5fa"},
    "Work":     {"icon": "💼", "color": "#fbbf24"},
    "Personal": {"icon": "🌸", "color": "#f472b6"},
    "Projects": {"icon": "🚀", "color": "#34d399"},
}
PRIORITIES = {"High": 0, "Medium": 1, "Low": 2}


# ---------- database ----------
def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL COLLATE NOCASE,
        password_hash TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        done INTEGER NOT NULL DEFAULT 0,
        done_on TEXT NOT NULL DEFAULT '',
        elapsed REAL NOT NULL DEFAULT 0,
        started REAL,
        color TEXT NOT NULL,
        category TEXT NOT NULL,
        priority TEXT NOT NULL,
        due TEXT NOT NULL DEFAULT '',
        target INTEGER NOT NULL DEFAULT 0,
        created TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS log (
        user_id INTEGER NOT NULL,
        day TEXT NOT NULL,
        category TEXT NOT NULL,
        seconds REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, day, category)
    );
    CREATE TABLE IF NOT EXISTS settings (
        user_id INTEGER PRIMARY KEY,
        goal INTEGER NOT NULL DEFAULT 3
    );
    """)
    con.commit()
    con.close()


init_db()


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ---------- login protection ----------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        uid = session.get("user_id")
        if not uid:
            return redirect(url_for("login"))
        row = get_db().execute("SELECT username FROM users WHERE id = ?", (uid,)).fetchone()
        if row is None:                      # account no longer exists
            session.clear()
            return redirect(url_for("login"))
        session["username"] = row["username"]
        return view(*args, **kwargs)
    return wrapped


# ---------- task helpers ----------
def ist_now():
    return datetime.now(IST)


def back():
    return redirect(request.referrer or url_for("home"))


def row_to_task(r):
    t = dict(r)
    t["done"] = bool(t["done"])
    return t


def get_tasks():
    rows = get_db().execute(
        "SELECT * FROM tasks WHERE user_id = ? ORDER BY id", (session["user_id"],)).fetchall()
    return [row_to_task(r) for r in rows]


def get_task(task_id):
    r = get_db().execute(
        "SELECT * FROM tasks WHERE id = ? AND user_id = ?", (task_id, session["user_id"])).fetchone()
    return row_to_task(r) if r else None


def save_task(t):
    db = get_db()
    db.execute(
        """UPDATE tasks SET title=?, done=?, done_on=?, elapsed=?, started=?, color=?,
           category=?, priority=?, due=?, target=? WHERE id=? AND user_id=?""",
        (t["title"], int(t["done"]), t["done_on"], t["elapsed"], t["started"], t["color"],
         t["category"], t["priority"], t["due"], t["target"], t["id"], session["user_id"]))
    db.commit()


def add_log(category, seconds):
    db = get_db()
    db.execute(
        """INSERT INTO log (user_id, day, category, seconds) VALUES (?, ?, ?, ?)
           ON CONFLICT(user_id, day, category) DO UPDATE SET seconds = seconds + excluded.seconds""",
        (session["user_id"], ist_now().date().isoformat(), category, round(seconds, 1)))
    db.commit()


def get_log(today):
    start = (today - timedelta(days=6)).isoformat()
    rows = get_db().execute(
        "SELECT day, category, seconds FROM log WHERE user_id = ? AND day >= ?",
        (session["user_id"], start)).fetchall()
    log = {}
    for r in rows:
        log.setdefault(r["day"], {})[r["category"]] = r["seconds"]
    return log


def get_goal():
    r = get_db().execute("SELECT goal FROM settings WHERE user_id = ?", (session["user_id"],)).fetchone()
    return r["goal"] if r else 3


def stop_timer(t):
    """Stops a running timer on the dict and logs the time. Caller must save_task(t)."""
    if t["started"] is not None:
        seg = time.time() - t["started"]
        t["elapsed"] += seg
        add_log(t["category"], seg)
        t["started"] = None


def fmt_hm(secs):
    secs = int(secs)
    h, m = secs // 3600, (secs % 3600) // 60
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m"
    return f"{secs}s" if secs else "0m"


def due_info(t, today):
    if not t["due"]:
        return {"due_text": "", "due_state": ""}
    d = date.fromisoformat(t["due"])
    diff = (d - today).days
    if t["done"]:
        return {"due_text": d.strftime("%d %b"), "due_state": "none"}
    if diff < 0:
        return {"due_text": f"Overdue by {-diff}d", "due_state": "overdue"}
    if diff == 0:
        return {"due_text": "Due today", "due_state": "today"}
    if diff == 1:
        return {"due_text": "Due tomorrow", "due_state": "soon"}
    if diff <= 3:
        return {"due_text": f"Due in {diff} days", "due_state": "soon"}
    return {"due_text": "Due " + d.strftime("%d %b"), "due_state": "none"}


def calc_streaks(tasks, today):
    dates = {t["done_on"] for t in tasks if t.get("done_on")}
    cur = 0
    d = today if today.isoformat() in dates else today - timedelta(days=1)
    while d.isoformat() in dates:
        cur += 1
        d -= timedelta(days=1)
    best = run = 0
    prev = None
    for iso in sorted(dates):
        dd = date.fromisoformat(iso)
        run = run + 1 if prev and (dd - prev).days == 1 else 1
        best = max(best, run)
        prev = dd
    return cur, best


def read_task_form(default_color):
    title = request.form.get("title", "").strip()[:200]

    color = request.form.get("color", "")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        color = default_color

    category = request.form.get("category", "Personal")
    if category not in CATEGORIES:
        category = "Personal"

    priority = request.form.get("priority", "Medium")
    if priority not in PRIORITIES:
        priority = "Medium"

    due = request.form.get("due", "")
    try:
        datetime.strptime(due, "%Y-%m-%d")
    except ValueError:
        due = ""

    try:
        minutes = max(0, min(999, int(request.form.get("minutes", "0") or 0)))
    except ValueError:
        minutes = 0

    return title, color, category, priority, due, minutes


def build_chart(tasks, log, today, running):
    now_t = time.time()
    days = []
    week_by_cat = {c: 0 for c in CATEGORIES}
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        iso = d.isoformat()
        per = {c: log.get(iso, {}).get(c, 0) for c in CATEGORIES}
        if running and i == 0:
            per[running["category"]] += now_t - running["started"]
        days.append({
            "label": d.strftime("%a"),
            "date": d.strftime("%d %b"),
            "per": per,
            "total": sum(per.values()),
            "done": sum(1 for t in tasks if t["done_on"] == iso),
            "today": i == 0,
        })
        for c in CATEGORIES:
            week_by_cat[c] += per[c]

    scale = max(max(d["total"] for d in days), 600)
    for d in days:
        d["segs"] = [
            {"cat": c, "color": CATEGORIES[c]["color"],
             "h": round(d["per"][c] / scale * 100, 1), "text": fmt_hm(d["per"][c])}
            for c in CATEGORIES if d["per"][c] > 0
        ]
        d["total_text"] = fmt_hm(d["total"]) if d["total"] else ""

    week_total = sum(d["total"] for d in days)
    best = max(days, key=lambda d: d["total"])
    return {
        "days": days,
        "week_total": fmt_hm(week_total),
        "avg": fmt_hm(week_total / 7),
        "best": best["label"] if best["total"] else "-",
        "legend": [{"name": c, "icon": CATEGORIES[c]["icon"], "color": CATEGORIES[c]["color"],
                    "text": fmt_hm(week_by_cat[c])} for c in CATEGORIES],
    }


# ---------- accounts ----------
@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("home"))
    error = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", username):
            error = "Username must be 3-20 characters: letters, numbers or underscore."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif password != confirm:
            error = "The two passwords do not match."
        else:
            db = get_db()
            try:
                cur = db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                                 (username, generate_password_hash(password)))
                db.commit()
            except sqlite3.IntegrityError:
                error = "That username is already taken."
            else:
                session.clear()
                session.permanent = True
                session["user_id"] = cur.lastrowid
                return redirect(url_for("home"))
    return render_template("auth.html", mode="register", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("home"))
    error = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        row = get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row and check_password_hash(row["password_hash"], password):
            session.clear()
            session.permanent = True
            session["user_id"] = row["id"]
            return redirect(url_for("home"))
        error = "Wrong username or password."
    return render_template("auth.html", mode="login", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- pages ----------
@app.route("/")
@login_required
def home():
    tasks = get_tasks()
    status = request.args.get("status", "all")
    cat = request.args.get("cat", "all")
    q = request.args.get("q", "").strip()
    sort = request.args.get("sort", "new")
    if status not in ("all", "pending", "completed"):
        status = "all"
    if cat != "all" and cat not in CATEGORIES:
        cat = "all"
    if sort not in ("new", "priority", "due"):
        sort = "new"

    today = ist_now().date()
    today_iso = today.isoformat()

    shown = list(tasks)
    if status == "pending":
        shown = [t for t in shown if not t["done"]]
    elif status == "completed":
        shown = [t for t in shown if t["done"]]
    if cat != "all":
        shown = [t for t in shown if t["category"] == cat]
    if q:
        shown = [t for t in shown if q.lower() in t["title"].lower()]

    far = "9999-12-31"
    if sort == "priority":
        shown.sort(key=lambda t: (PRIORITIES[t["priority"]], t["due"] or far))
    elif sort == "due":
        shown.sort(key=lambda t: t["due"] or far)

    view = [dict(t, **due_info(t, today)) for t in shown]

    total = len(tasks)
    done = sum(1 for t in tasks if t["done"])
    by_cat = {}
    for name in CATEGORIES:
        c_total = sum(1 for t in tasks if t["category"] == name)
        c_done = sum(1 for t in tasks if t["category"] == name and t["done"])
        by_cat[name] = {
            "total": c_total,
            "done": c_done,
            "pct": round(c_done / c_total * 100) if c_total else 0,
        }
    done_today = sum(1 for t in tasks if t["done_on"] == today_iso)
    stats = {
        "total": total,
        "done": done,
        "pending": total - done,
        "pct": round(done / total * 100) if total else 0,
        "overdue": sum(1 for t in tasks if not t["done"] and t["due"] and t["due"] < today_iso),
        "due_today": sum(1 for t in tasks if not t["done"] and t["due"] == today_iso),
        "done_today": done_today,
        "by_cat": by_cat,
        "by_prio": {p: sum(1 for t in tasks if not t["done"] and t["priority"] == p)
                    for p in PRIORITIES},
    }

    goal = get_goal()
    streak, best_streak = calc_streaks(tasks, today)
    goal_info = {
        "goal": goal,
        "done": done_today,
        "pct": min(done_today / goal, 1) if goal else 0,
        "reached": done_today >= goal,
        "streak": streak,
        "best": best_streak,
    }

    total_elapsed = sum(t["elapsed"] for t in tasks)
    running = next((t for t in tasks if t["started"] is not None), None)
    chart = build_chart(tasks, get_log(today), today, running)

    def link(**changes):
        params = {"status": status, "cat": cat, "q": q, "sort": sort}
        params.update(changes)
        params = {k: v for k, v in params.items() if v and v not in ("all", "new")}
        return url_for("home", **params)

    return render_template(
        "index.html",
        tasks=view, stats=stats, cats=CATEGORIES, prios=PRIORITIES,
        status=status, cat=cat, q=q, sort=sort, link=link,
        has_tasks=bool(tasks), running=running, total_elapsed=total_elapsed,
        now=time.time(), chart=chart, goal=goal_info,
        default_color=PALETTE[len(tasks) % len(PALETTE)],
        today_iso=today_iso, username=session.get("username", ""),
    )


@app.route("/add", methods=["POST"])
@login_required
def add():
    db = get_db()
    count = db.execute("SELECT COUNT(*) FROM tasks WHERE user_id = ?", (session["user_id"],)).fetchone()[0]
    title, color, category, priority, due, minutes = read_task_form(PALETTE[count % len(PALETTE)])
    if title:
        db.execute(
            """INSERT INTO tasks (user_id, title, color, category, priority, due, target, created)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session["user_id"], title, color, category, priority, due, minutes * 60,
             ist_now().strftime("%d %b, %I:%M %p")))
        db.commit()
    return redirect(url_for("home"))


@app.route("/edit/<int:task_id>", methods=["POST"])
@login_required
def edit(task_id):
    t = get_task(task_id)
    if t:
        title, color, category, priority, due, minutes = read_task_form(t["color"])
        if title:
            if category != t["category"] and t["started"] is not None:
                stop_timer(t)
            t.update({"title": title, "color": color, "category": category,
                      "priority": priority, "due": due, "target": minutes * 60})
            save_task(t)
    return back()


@app.route("/goal", methods=["POST"])
@login_required
def set_goal():
    try:
        goal = max(1, min(50, int(request.form.get("goal", "3"))))
    except ValueError:
        return back()
    db = get_db()
    db.execute("""INSERT INTO settings (user_id, goal) VALUES (?, ?)
                  ON CONFLICT(user_id) DO UPDATE SET goal = excluded.goal""",
               (session["user_id"], goal))
    db.commit()
    return back()


@app.route("/complete/<int:task_id>")
@login_required
def complete(task_id):
    t = get_task(task_id)
    if t:
        t["done"] = not t["done"]
        if t["done"]:
            stop_timer(t)
            t["done_on"] = ist_now().date().isoformat()
        else:
            t["done_on"] = ""
        save_task(t)
    return back()


@app.route("/timer/<int:task_id>")
@login_required
def timer(task_id):
    t = get_task(task_id)
    if t and not t["done"]:
        if t["started"] is None:
            for other in get_tasks():
                if other["started"] is not None:
                    stop_timer(other)
                    save_task(other)
            t["started"] = time.time()
        else:
            stop_timer(t)
        save_task(t)
    return back()


@app.route("/reset/<int:task_id>")
@login_required
def reset(task_id):
    t = get_task(task_id)
    if t:
        stop_timer(t)
        t["elapsed"] = 0.0
        save_task(t)
    return back()


@app.route("/delete/<int:task_id>")
@login_required
def delete(task_id):
    t = get_task(task_id)
    if t:
        stop_timer(t)
        db = get_db()
        db.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, session["user_id"]))
        db.commit()
    return back()


if __name__ == "__main__":
    app.run(debug=True)
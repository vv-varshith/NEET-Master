import os, json, random, sqlite3, time
from pathlib import Path
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import requests

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-key-before-deployment")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
DB_PATH = BASE_DIR / "data" / "neet_master.db"
BANK_PATH = BASE_DIR / "data" / "questions.json"
SUBJECTS = ["Physics", "Chemistry", "Botany", "Zoology"]

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, mobile TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, created_at TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL, mode TEXT NOT NULL, subject TEXT,
            topic TEXT, total INTEGER NOT NULL, correct INTEGER NOT NULL,
            score REAL NOT NULL, created_at TEXT NOT NULL,
            attempted INTEGER NOT NULL DEFAULT 0,
            wrong INTEGER NOT NULL DEFAULT 0,
            unanswered INTEGER NOT NULL DEFAULT 0,
            max_score REAL NOT NULL DEFAULT 0)""")
        # Safe schema migration for databases created by earlier versions.
        cols = {row[1] for row in conn.execute("PRAGMA table_info(attempts)")}
        for column, definition in {
            "attempted": "INTEGER NOT NULL DEFAULT 0",
            "wrong": "INTEGER NOT NULL DEFAULT 0",
            "unanswered": "INTEGER NOT NULL DEFAULT 0",
            "max_score": "REAL NOT NULL DEFAULT 0",
        }.items():
            if column not in cols:
                conn.execute(f"ALTER TABLE attempts ADD COLUMN {column} {definition}")
        conn.execute("""CREATE TABLE IF NOT EXISTS bookmarks (
            student_id TEXT NOT NULL, question_id TEXT NOT NULL,
            created_at TEXT NOT NULL, PRIMARY KEY(student_id, question_id))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS generated_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT NOT NULL,
            subject TEXT NOT NULL, topic TEXT NOT NULL, payload TEXT NOT NULL,
            created_at TEXT NOT NULL)""")

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("account_id"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Please log in to continue."}), 401
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapped

def student_id():
    return str(session["account_id"])

def load_bank():
    with open(BANK_PATH, encoding="utf-8") as f:
        return json.load(f)

def all_questions():
    questions = list(load_bank())
    with db() as conn:
        rows = conn.execute("SELECT payload FROM generated_questions WHERE student_id=?", (student_id(),)).fetchall()
    for row in rows:
        try:
            questions.extend(json.loads(row["payload"]))
        except Exception:
            pass
    return questions

@app.route("/")
def home():
    if not session.get("account_id"):
        return redirect(url_for("login"))
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("account_id"):
        return redirect(url_for("home"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        mobile = request.form.get("mobile", "").strip()
        password = request.form.get("password", "").strip()
        if not name or not name.replace(" ", "").isalpha():
            flash("Please enter a valid name.", "error")
        elif not (mobile.isdigit() and len(mobile) == 10 and mobile[0] in "6789"):
            flash("Enter a valid 10-digit Indian mobile number.", "error")
        elif password != mobile[-4:]:
            flash("For this login mode, password must match the last 4 digits of your mobile number.", "error")
        else:
            try:
                with db() as conn:
                    cur = conn.execute("INSERT INTO students(name,mobile,password_hash,created_at) VALUES(?,?,?,?)",
                        (name, mobile, generate_password_hash(password), datetime.now().isoformat(timespec="seconds")))
                    session.clear()
                    session["account_id"] = str(cur.lastrowid)
                    session["student_name"] = name
                    session["mobile"] = mobile
                return redirect(url_for("home"))
            except sqlite3.IntegrityError:
                flash("This mobile number is already registered. Please log in.", "error")
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("account_id"):
        return redirect(url_for("home"))
    if request.method == "POST":
        mobile = request.form.get("mobile", "").strip()
        password = request.form.get("password", "").strip()
        with db() as conn:
            user = conn.execute("SELECT * FROM students WHERE mobile=?", (mobile,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["account_id"] = str(user["id"])
            session["student_name"] = user["name"]
            session["mobile"] = user["mobile"]
            return redirect(url_for("home"))
        flash("Invalid mobile number or password.", "error")
    return render_template("login.html")

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.get("/api/me")
@login_required
def me():
    return jsonify({"name": session.get("student_name", "Student"), "mobile": session.get("mobile", "")})

@app.get("/api/meta")
@login_required
def meta():
    qs = all_questions()
    subjects = {}
    for s in SUBJECTS:
        sq = [q for q in qs if q["subject"] == s]
        subjects[s] = {"count": len(sq), "topics": sorted(set(q["topic"] for q in sq))}
    return jsonify({"subjects": subjects, "total": len(qs), "ai_enabled": bool(os.getenv("GEMINI_API_KEY"))})

@app.get("/api/questions")
@login_required
def questions():
    subject = request.args.get("subject", "All")
    topic = request.args.get("topic", "All")
    search = request.args.get("search", "").strip().lower()
    mode = request.args.get("mode", "practice")
    try:
        limit = min(max(int(request.args.get("limit", 30)), 1), 180)
    except ValueError:
        return jsonify({"error": "Invalid question limit."}), 400
    qs = all_questions()
    if subject != "All": qs = [q for q in qs if q.get("subject") == subject]
    if topic != "All": qs = [q for q in qs if q.get("topic") == topic]
    if search:
        qs = [q for q in qs if search in q.get("question", "").lower() or search in q.get("topic", "").lower() or search in q.get("subject", "").lower()]
    if mode == "mock":
        exam_type = request.args.get("exam_type", "mini")
        if exam_type == "full":
            physics = [q for q in qs if q.get("subject") == "Physics"]
            chemistry = [q for q in qs if q.get("subject") == "Chemistry"]
            biology = [q for q in qs if q.get("subject") in ("Botany", "Zoology")]
            required = {"Physics": 45, "Chemistry": 45, "Biology": 90}
            available = {"Physics": len(physics), "Chemistry": len(chemistry), "Biology": len(biology)}
            if any(available[k] < required[k] for k in required):
                return jsonify({"error": "Full NEET mock test needs 180 unique questions: 45 Physics, 45 Chemistry and 90 Biology. Current bank: " + ", ".join(f"{k} {available[k]}/{required[k]}" for k in required) + ". Add more questions to the question bank before starting." , "required": required, "available": available}), 400
            qs = random.sample(physics, 45) + random.sample(chemistry, 45) + random.sample(biology, 90)
            random.shuffle(qs)
        else:
            if len(qs) < 45:
                return jsonify({"error": f"Mini mock test needs 45 unique questions. Only {len(qs)} are currently available."}), 400
            qs = random.sample(qs, 45)
    else:
        qs.sort(key=lambda q: (q.get("subject", ""), q.get("topic", ""), str(q.get("id", ""))))
        qs = qs[:limit]
    return jsonify({"questions": qs, "count": len(qs)})

@app.post("/api/attempts")
@login_required
def save_attempt():
    data = request.get_json(silent=True) or {}
    responses = data.get("responses")
    mode = str(data.get("mode", "Practice"))[:40]
    if not isinstance(responses, list) or not responses:
        return jsonify({"error": "No test responses were submitted."}), 400
    if len(responses) not in (45, 180):
        return jsonify({"error": "A mock test must contain 45 or 180 questions."}), 400
    bank = {str(q.get("id")): q for q in all_questions()}
    correct = wrong = attempted = 0
    seen = set()
    for item in responses:
        if not isinstance(item, dict) or "id" not in item:
            return jsonify({"error": "Invalid answer data."}), 400
        qid = str(item["id"])
        if qid in seen or qid not in bank:
            return jsonify({"error": "Question data is invalid or duplicated. Please restart the test."}), 400
        seen.add(qid)
        chosen = item.get("answer")
        if chosen is not None:
            if not isinstance(chosen, int) or chosen not in range(4):
                return jsonify({"error": "Invalid selected option."}), 400
            attempted += 1
            if chosen == bank[qid].get("answer"):
                correct += 1
            else:
                wrong += 1
    total = len(responses)
    unanswered = total - attempted
    score = correct * 4 - wrong
    max_score = total * 4
    with db() as conn:
        conn.execute("""INSERT INTO attempts(student_id,mode,subject,topic,total,correct,score,created_at,attempted,wrong,unanswered,max_score)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (student_id(), mode, None, None, total, correct, score,
        datetime.now().isoformat(timespec="seconds"), attempted, wrong, unanswered, max_score))
    return jsonify({"saved": True, "total": total, "attempted": attempted, "correct": correct,
        "wrong": wrong, "unanswered": unanswered, "score": score, "max_score": max_score})

@app.get("/api/progress")
@login_required
def progress():
    with db() as conn:
        rows = conn.execute("SELECT * FROM attempts WHERE student_id=? ORDER BY id DESC LIMIT 20", (student_id(),)).fetchall()
        count = conn.execute("SELECT COUNT(*) n FROM attempts WHERE student_id=?", (student_id(),)).fetchone()["n"]
        avg = conn.execute("SELECT AVG(CASE WHEN max_score > 0 THEN (score * 720.0 / max_score) ELSE score END) a FROM attempts WHERE student_id=?", (student_id(),)).fetchone()["a"]
        bookmarks = conn.execute("SELECT question_id FROM bookmarks WHERE student_id=?", (student_id(),)).fetchall()
    return jsonify({"attempts":[dict(r) for r in rows], "attempt_count":count,
        "average_score": round(avg or 0, 1), "bookmarks":[r["question_id"] for r in bookmarks]})

@app.post("/api/bookmark")
@login_required
def bookmark():
    data = request.get_json(force=True); qid = str(data.get("question_id",""))
    if not qid: return jsonify({"error":"question_id required"}), 400
    with db() as conn:
        exists = conn.execute("SELECT 1 FROM bookmarks WHERE student_id=? AND question_id=?", (student_id(),qid)).fetchone()
        if exists:
            conn.execute("DELETE FROM bookmarks WHERE student_id=? AND question_id=?", (student_id(),qid))
            saved = False
        else:
            conn.execute("INSERT OR IGNORE INTO bookmarks VALUES(?,?,?)", (student_id(),qid,datetime.now().isoformat()))
            saved = True
    return jsonify({"saved":saved})

@app.get("/api/bookmarks")
@login_required
def get_bookmarks():
    ids = set(progress().json["bookmarks"])
    return jsonify({"questions":[q for q in all_questions() if str(q["id"]) in ids]})

@app.post("/api/generate")
@login_required
def generate():
    data = request.get_json(force=True)
    subject = data.get("subject","Biology")
    topic = data.get("topic","")
    count = min(max(int(data.get("count",5)),1),10)
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error":"AI generation is not configured. Add GEMINI_API_KEY to .env. The built-in question bank still works."}), 503
    prompt = f"""Create {count} original NEET-UG style multiple choice questions.
Subject: {subject}. Topic: {topic}. Return ONLY valid JSON array. Each item must have:
question (string), options (array of exactly 4 strings), answer (zero-based integer 0-3), explanation (string), subject (string), topic (string), difficulty (Easy/Medium/Hard).
Do not include markdown. Questions must be scientifically accurate and original."""
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=" + api_key
        response = requests.post(url, json={"contents":[{"parts":[{"text":prompt}]}],
            "generationConfig":{"temperature":0.45,"responseMimeType":"application/json"}}, timeout=45)
        response.raise_for_status()
        raw = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        generated = json.loads(raw)
        valid = []
        for i, q in enumerate(generated):
            if isinstance(q,dict) and isinstance(q.get("question"),str) and isinstance(q.get("options"),list) and len(q["options"])==4 and isinstance(q.get("answer"),int) and 0 <= q["answer"] <= 3:
                q.update({"id":f"ai-{int(time.time())}-{i}", "subject":subject, "topic":topic or q.get("topic","Generated"), "difficulty":q.get("difficulty","Medium"), "source":"AI generated"})
                valid.append(q)
        if not valid: return jsonify({"error":"The AI response did not contain valid MCQs. Try again."}), 502
        with db() as conn:
            conn.execute("INSERT INTO generated_questions(student_id,subject,topic,payload,created_at) VALUES(?,?,?,?,?)",
                (student_id(),subject,topic,json.dumps(valid),datetime.now().isoformat()))
        return jsonify({"questions":valid,"count":len(valid)})
    except requests.RequestException as e:
        return jsonify({"error":f"AI service connection failed: {e}"}), 502
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        return jsonify({"error":f"Could not read AI response: {e}"}), 502

@app.get("/health")
def health():
    return jsonify({"status":"ok","app":"NEET Master"})

@app.errorhandler(404)
def not_found(_):
    if request.path.startswith("/api/"): return jsonify({"error":"API endpoint not found"}),404
    return "Page not found",404

init_db()
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT",5000)), debug=os.getenv("FLASK_DEBUG","0")=="1")

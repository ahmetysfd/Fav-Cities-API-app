from flask import Flask, request, jsonify, render_template, session, redirect
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, requests
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = "skywatch_secret_key_2024_change_in_prod"
WEATHER_API_KEY = "3bac4e88f67a52186b7cbc5c22155ad3"

def get_db():
    c = sqlite3.connect("database.db")
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = get_db()
    cur = c.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, last_login TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS cities(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
        city_name TEXT NOT NULL, country_code TEXT DEFAULT '',
        visited INTEGER DEFAULT 0, lat REAL DEFAULT NULL, lon REAL DEFAULT NULL,
        added_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users(id))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS city_images(
        city_name TEXT PRIMARY KEY, image_url TEXT, wiki_description TEXT, cached_at TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS reviews(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, city_name TEXT NOT NULL,
        rating INTEGER NOT NULL CHECK(rating>=1 AND rating<=10), comment TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT,
        UNIQUE(user_id, city_name), FOREIGN KEY (user_id) REFERENCES users(id))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS notes(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, city_name TEXT NOT NULL,
        content TEXT DEFAULT '', updated_at TEXT,
        UNIQUE(user_id, city_name), FOREIGN KEY (user_id) REFERENCES users(id))""")
    for col in ["country_code TEXT DEFAULT ''", "visited INTEGER DEFAULT 0",
                "lat REAL DEFAULT NULL", "lon REAL DEFAULT NULL"]:
        try: cur.execute(f"ALTER TABLE cities ADD COLUMN {col}")
        except: pass
    c.commit(); c.close()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session: return jsonify({"message":"Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

def fetch_city_image(city):
    c = get_db()
    cached = c.execute("SELECT image_url, wiki_description FROM city_images WHERE city_name=?", (city,)).fetchone()
    c.close()
    if cached: return {"image_url": cached["image_url"], "wiki_description": cached["wiki_description"]}
    image_url = wiki_description = None
    for term in [city, f"{city} city"]:
        try:
            r = requests.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(term)}",
                             headers={"User-Agent":"SkyWatch/1.0"}, timeout=6)
            if r.status_code == 200:
                d = r.json()
                img = d.get("originalimage") or d.get("thumbnail")
                if img and img.get("source"):
                    image_url = img["source"]
                    wiki_description = d.get("extract","")[:300]
                    break
        except: continue
    if not image_url:
        image_url = f"https://picsum.photos/seed/{city.replace(' ','').lower()}/900/500"
        wiki_description = ""
    c = get_db()
    c.execute("INSERT OR REPLACE INTO city_images VALUES (?,?,?,?)",
              (city, image_url, wiki_description, datetime.now().isoformat()))
    c.commit(); c.close()
    return {"image_url": image_url, "wiki_description": wiki_description or ""}

def get_weather(city):
    try:
        r = requests.get(f"https://api.openweathermap.org/data/2.5/weather?q={city.title()}&appid={WEATHER_API_KEY}&units=metric", timeout=6)
        d = r.json()
    except: return {"city": city, "error": True}
    if d.get("cod") != 200: return {"city": city, "error": True, "description": "City not found"}
    icon = d["weather"][0]["icon"]
    return {
        "city": d["name"], "country": d["sys"]["country"],
        "lat": d["coord"]["lat"], "lon": d["coord"]["lon"],
        "temp": round(d["main"]["temp"]), "feels_like": round(d["main"]["feels_like"]),
        "temp_min": round(d["main"]["temp_min"]), "temp_max": round(d["main"]["temp_max"]),
        "humidity": d["main"]["humidity"], "wind_speed": round(d["wind"]["speed"]*3.6, 1),
        "description": d["weather"][0]["description"].title(),
        "weather_main": d["weather"][0]["main"],
        "icon": f"https://openweathermap.org/img/wn/{icon}@2x.png",
        "visibility": round(d.get("visibility",0)/1000, 1),
        "pressure": d["main"]["pressure"],
        "sunrise": datetime.utcfromtimestamp(d["sys"]["sunrise"]).strftime("%H:%M"),
        "sunset": datetime.utcfromtimestamp(d["sys"]["sunset"]).strftime("%H:%M"),
    }

@app.route("/")
def home():
    if "user_id" in session: return redirect("/dashboard")
    return render_template("index.html")

@app.route("/dashboard")
def dashboard():
    if "user_id" not in session: return redirect("/")
    return render_template("dashboard.html")

@app.route("/register", methods=["POST"])
def register():
    data = request.get_json()
    username = data.get("username","").strip().lower()
    password = data.get("password","")
    if len(username) < 3: return jsonify({"message":"Username must be at least 3 characters."}), 400
    if len(password) < 6: return jsonify({"message":"Password must be at least 6 characters."}), 400
    c = get_db()
    if c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone():
        c.close(); return jsonify({"message":"Username already taken."}), 409
    c.execute("INSERT INTO users (username,password) VALUES (?,?)", (username, generate_password_hash(password)))
    c.commit(); c.close()
    return jsonify({"message":"Account created! You can now log in."})

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get("username","").strip().lower()
    password = data.get("password","")
    c = get_db()
    user = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if user and check_password_hash(user["password"], password):
        c.execute("UPDATE users SET last_login=? WHERE id=?", (datetime.now().isoformat(), user["id"]))
        c.commit(); c.close()
        session["user_id"] = user["id"]; session["username"] = user["username"]
        return jsonify({"message":"Login successful!", "username": user["username"]})
    c.close(); return jsonify({"message":"Invalid username or password."}), 401

@app.route("/logout")
def logout():
    session.clear(); return redirect("/")

@app.route("/get-user")
@login_required
def get_user():
    c = get_db()
    cnt = c.execute("SELECT COUNT(*) as n FROM cities WHERE user_id=?", (session["user_id"],)).fetchone()
    vis = c.execute("SELECT COUNT(*) as n FROM cities WHERE user_id=? AND visited=1", (session["user_id"],)).fetchone()
    ctr = c.execute("SELECT COUNT(DISTINCT country_code) as n FROM cities WHERE user_id=? AND country_code!=''", (session["user_id"],)).fetchone()
    c.close()
    return jsonify({"username": session["username"], "user_id": session["user_id"],
                    "city_count": cnt["n"], "visited_count": vis["n"], "country_count": ctr["n"]})

@app.route("/add-city", methods=["POST"])
@login_required
def add_city():
    data = request.get_json()
    city = data.get("city","").strip().title()
    uid = session["user_id"]
    if not city: return jsonify({"message":"Please enter a city name."}), 400
    w = get_weather(city)
    if w.get("error"): return jsonify({"message":f"'{city}' not found. Check the spelling."}), 404
    c = get_db()
    if c.execute("SELECT id FROM cities WHERE user_id=? AND city_name=?", (uid, w["city"])).fetchone():
        c.close(); return jsonify({"message":f"{w['city']} is already in your library."}), 409
    c.execute("INSERT INTO cities (user_id,city_name,country_code,lat,lon) VALUES (?,?,?,?,?)",
              (uid, w["city"], w.get("country",""), w.get("lat"), w.get("lon")))
    c.commit(); c.close()
    img = fetch_city_image(w["city"])
    return jsonify({"message":"City added!", "weather": w, "image": img})

@app.route("/delete-city", methods=["POST"])
@login_required
def delete_city():
    data = request.get_json()
    c = get_db()
    c.execute("DELETE FROM cities WHERE city_name=? AND user_id=?", (data["city"], session["user_id"]))
    c.commit(); c.close()
    return jsonify({"message":"Deleted"})

@app.route("/toggle-visited", methods=["POST"])
@login_required
def toggle_visited():
    data = request.get_json()
    c = get_db()
    row = c.execute("SELECT visited FROM cities WHERE city_name=? AND user_id=?",
                    (data["city"], session["user_id"])).fetchone()
    if row:
        new_val = 0 if row["visited"] else 1
        c.execute("UPDATE cities SET visited=? WHERE city_name=? AND user_id=?",
                  (new_val, data["city"], session["user_id"]))
        c.commit(); c.close()
        return jsonify({"visited": bool(new_val)})
    c.close(); return jsonify({"message":"City not found"}), 404

@app.route("/get-cities")
@login_required
def get_cities():
    c = get_db()
    rows = c.execute("SELECT city_name, visited, lat, lon FROM cities WHERE user_id=? ORDER BY added_at ASC",
                     (session["user_id"],)).fetchall()
    c.close()
    results = []
    for row in rows:
        w = get_weather(row["city_name"])
        if not w.get("error"):
            img = fetch_city_image(row["city_name"])
            w["image_url"] = img["image_url"]
            w["wiki_description"] = img["wiki_description"]
            w["visited"] = bool(row["visited"])
            # Use stored lat/lon if available, fall back to weather API coords
            w["lat"] = row["lat"] if row["lat"] is not None else w.get("lat")
            w["lon"] = row["lon"] if row["lon"] is not None else w.get("lon")
            c2 = get_db()
            avg = c2.execute("SELECT AVG(rating) as a, COUNT(*) as ct FROM reviews WHERE city_name=?",
                             (row["city_name"],)).fetchone()
            c2.close()
            w["avg_rating"] = round(avg["a"], 1) if avg["a"] else None
            w["review_count"] = avg["ct"]
            results.append(w)
    return jsonify(results)

@app.route("/get-reviews/<city_name>")
@login_required
def get_reviews(city_name):
    c = get_db()
    reviews = c.execute("""SELECT r.id,r.rating,r.comment,r.created_at,r.updated_at,u.username,r.user_id
        FROM reviews r JOIN users u ON r.user_id=u.id WHERE r.city_name=? ORDER BY r.created_at DESC""",
        (city_name,)).fetchall()
    avg = c.execute("SELECT AVG(rating) as a, COUNT(*) as ct FROM reviews WHERE city_name=?", (city_name,)).fetchone()
    my = c.execute("SELECT rating,comment FROM reviews WHERE city_name=? AND user_id=?",
                   (city_name, session["user_id"])).fetchone()
    c.close()
    return jsonify({"reviews":[dict(r) for r in reviews],
                    "avg_rating": round(avg["a"],1) if avg["a"] else None,
                    "count": avg["ct"], "my_review": dict(my) if my else None})

@app.route("/add-review", methods=["POST"])
@login_required
def add_review():
    data = request.get_json()
    city, rating, comment = data.get("city","").strip(), data.get("rating"), data.get("comment","").strip()
    if not city or rating is None: return jsonify({"message":"City and rating required."}), 400
    if not isinstance(rating, int) or not (1 <= rating <= 10): return jsonify({"message":"Rating must be 1-10."}), 400
    c = get_db()
    if c.execute("SELECT id FROM reviews WHERE user_id=? AND city_name=?", (session["user_id"], city)).fetchone():
        c.execute("UPDATE reviews SET rating=?,comment=?,updated_at=? WHERE user_id=? AND city_name=?",
                  (rating, comment, datetime.now().isoformat(), session["user_id"], city))
        msg = "Review updated!"
    else:
        c.execute("INSERT INTO reviews (user_id,city_name,rating,comment) VALUES (?,?,?,?)",
                  (session["user_id"], city, rating, comment))
        msg = "Review posted!"
    c.commit(); c.close()
    return jsonify({"message": msg})

@app.route("/delete-review", methods=["POST"])
@login_required
def delete_review():
    data = request.get_json()
    c = get_db()
    c.execute("DELETE FROM reviews WHERE city_name=? AND user_id=?", (data["city"], session["user_id"]))
    c.commit(); c.close()
    return jsonify({"message":"Review deleted."})

@app.route("/get-note/<city_name>")
@login_required
def get_note(city_name):
    c = get_db()
    note = c.execute("SELECT content, updated_at FROM notes WHERE city_name=? AND user_id=?",
                     (city_name, session["user_id"])).fetchone()
    c.close()
    return jsonify({"content": note["content"] if note else "", "updated_at": note["updated_at"] if note else None})

@app.route("/save-note", methods=["POST"])
@login_required
def save_note():
    data = request.get_json()
    city = data.get("city","").strip()
    content = data.get("content","").strip()
    if not city: return jsonify({"message":"City required."}), 400
    c = get_db()
    if c.execute("SELECT id FROM notes WHERE user_id=? AND city_name=?", (session["user_id"], city)).fetchone():
        c.execute("UPDATE notes SET content=?,updated_at=? WHERE user_id=? AND city_name=?",
                  (content, datetime.now().isoformat(), session["user_id"], city))
    else:
        c.execute("INSERT INTO notes (user_id,city_name,content,updated_at) VALUES (?,?,?,?)",
                  (session["user_id"], city, content, datetime.now().isoformat()))
    c.commit(); c.close()
    return jsonify({"message":"Note saved."})

@app.route("/get-forecast/<city_name>")
@login_required
def get_forecast(city_name):
    try:
        r = requests.get(
            f"https://api.openweathermap.org/data/2.5/forecast?q={city_name}&appid={WEATHER_API_KEY}&cnt=8&units=metric",
            timeout=6)
        d = r.json()
        if d.get("cod") != "200": return jsonify({"error": True})
        points = [{"time": item["dt_txt"][11:16], "temp": round(item["main"]["temp"]),
                   "icon": item["weather"][0]["icon"],
                   "desc": item["weather"][0]["description"].title()}
                  for item in d["list"]]
        return jsonify({"points": points})
    except: return jsonify({"error": True})

if __name__ == "__main__":
    init_db()
    app.run(debug=True)

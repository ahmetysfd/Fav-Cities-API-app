from flask import Flask, request, jsonify, render_template, session, redirect
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import requests
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = "skywatch_secret_key_2024_change_in_prod"

WEATHER_API_KEY = "3bac4e88f67a52186b7cbc5c22155ad3"

# ---------- DATABASE ----------
def get_db_connection():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_login TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cities(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            city_name TEXT NOT NULL,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS city_images(
            city_name TEXT PRIMARY KEY,
            image_url TEXT,
            wiki_description TEXT,
            cached_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reviews(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            city_name TEXT NOT NULL,
            rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 10),
            comment TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT,
            UNIQUE(user_id, city_name),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    conn.commit()
    conn.close()

# ---------- AUTH DECORATOR ----------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"message": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

# ---------- CITY IMAGE (Wikipedia) ----------
def fetch_city_image(city):
    conn = get_db_connection()
    cached = conn.execute("SELECT image_url, wiki_description FROM city_images WHERE city_name=?",
                          (city,)).fetchone()
    conn.close()
    if cached:
        return {"image_url": cached["image_url"], "wiki_description": cached["wiki_description"]}

    image_url = None
    wiki_description = ""
    search_terms = [city, f"{city} city"]

    for term in search_terms:
        try:
            url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(term)}"
            resp = requests.get(url, headers={"User-Agent": "SkyWatch/1.0"}, timeout=6)
            if resp.status_code == 200:
                data = resp.json()
                img = data.get("originalimage") or data.get("thumbnail")
                if img and img.get("source"):
                    image_url = img["source"]
                    wiki_description = data.get("extract", "")[:300]
                    break
        except Exception:
            continue

    if not image_url:
        # Deterministic landscape fallback using city name as seed
        image_url = f"https://picsum.photos/seed/{city.replace(' ', '').lower()}/900/500"
        wiki_description = ""

    conn = get_db_connection()
    conn.execute("""
        INSERT OR REPLACE INTO city_images (city_name, image_url, wiki_description, cached_at)
        VALUES (?,?,?,?)
    """, (city, image_url, wiki_description, datetime.now().isoformat()))
    conn.commit()
    conn.close()

    return {"image_url": image_url, "wiki_description": wiki_description}

# ---------- WEATHER ----------
def get_weather(city):
    city = city.title()
    url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric"
    try:
        response = requests.get(url, timeout=6)
        data = response.json()
    except Exception:
        return {"city": city, "error": True}

    if data.get("cod") != 200:
        return {"city": city, "error": True, "description": "City not found", "icon": ""}

    icon = data["weather"][0]["icon"]
    return {
        "city": data["name"],
        "country": data["sys"]["country"],
        "temp": round(data["main"]["temp"]),
        "feels_like": round(data["main"]["feels_like"]),
        "temp_min": round(data["main"]["temp_min"]),
        "temp_max": round(data["main"]["temp_max"]),
        "humidity": data["main"]["humidity"],
        "wind_speed": round(data["wind"]["speed"] * 3.6, 1),
        "description": data["weather"][0]["description"].title(),
        "weather_main": data["weather"][0]["main"],
        "icon": f"https://openweathermap.org/img/wn/{icon}@2x.png",
        "visibility": round(data.get("visibility", 0) / 1000, 1),
        "pressure": data["main"]["pressure"],
        "sunrise": datetime.utcfromtimestamp(data["sys"]["sunrise"]).strftime("%H:%M"),
        "sunset": datetime.utcfromtimestamp(data["sys"]["sunset"]).strftime("%H:%M"),
    }

# ---------- AUTH ROUTES ----------
@app.route("/")
def home():
    if "user_id" in session:
        return redirect("/dashboard")
    return render_template("index.html")

@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/")
    return render_template("dashboard.html")

@app.route("/register", methods=["POST"])
def register():
    data = request.get_json()
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")
    if len(username) < 3:
        return jsonify({"message": "Username must be at least 3 characters."}), 400
    if len(password) < 6:
        return jsonify({"message": "Password must be at least 6 characters."}), 400
    conn = get_db_connection()
    if conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone():
        conn.close()
        return jsonify({"message": "Username already taken."}), 409
    conn.execute("INSERT INTO users (username, password) VALUES (?,?)",
                 (username, generate_password_hash(password)))
    conn.commit()
    conn.close()
    return jsonify({"message": "Account created! You can now log in."})

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if user and check_password_hash(user["password"], password):
        conn.execute("UPDATE users SET last_login=? WHERE id=?",
                     (datetime.now().isoformat(), user["id"]))
        conn.commit()
        conn.close()
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        return jsonify({"message": "Login successful!", "username": user["username"]})
    conn.close()
    return jsonify({"message": "Invalid username or password."}), 401

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/get-user")
@login_required
def get_user():
    conn = get_db_connection()
    user = conn.execute("SELECT created_at FROM users WHERE id=?", (session["user_id"],)).fetchone()
    count = conn.execute("SELECT COUNT(*) as c FROM cities WHERE user_id=?",
                         (session["user_id"],)).fetchone()
    conn.close()
    return jsonify({
        "username": session["username"],
        "user_id": session["user_id"],
        "city_count": count["c"],
        "member_since": user["created_at"][:10] if user and user["created_at"] else "N/A",
    })

# ---------- CITY ROUTES ----------
@app.route("/add-city", methods=["POST"])
@login_required
def add_city():
    data = request.get_json()
    city = data.get("city", "").strip().title()
    user_id = session["user_id"]
    if not city:
        return jsonify({"message": "Please enter a city name."}), 400
    weather = get_weather(city)
    if weather.get("error"):
        return jsonify({"message": f"'{city}' not found. Check the spelling."}), 404
    conn = get_db_connection()
    if conn.execute("SELECT id FROM cities WHERE user_id=? AND city_name=?",
                    (user_id, weather["city"])).fetchone():
        conn.close()
        return jsonify({"message": f"{weather['city']} is already in your library."}), 409
    conn.execute("INSERT INTO cities (user_id, city_name) VALUES (?,?)",
                 (user_id, weather["city"]))
    conn.commit()
    conn.close()
    city_image = fetch_city_image(weather["city"])
    return jsonify({"message": "City added!", "weather": weather, "image": city_image})

@app.route("/delete-city", methods=["POST"])
@login_required
def delete_city():
    data = request.get_json()
    conn = get_db_connection()
    conn.execute("DELETE FROM cities WHERE city_name=? AND user_id=?",
                 (data["city"], session["user_id"]))
    conn.commit()
    conn.close()
    return jsonify({"message": "Deleted"})

@app.route("/get-cities")
@login_required
def get_cities():
    conn = get_db_connection()
    cities = conn.execute("SELECT city_name FROM cities WHERE user_id=? ORDER BY added_at ASC",
                          (session["user_id"],)).fetchall()
    conn.close()
    results = []
    for row in cities:
        name = row["city_name"]
        weather = get_weather(name)
        if not weather.get("error"):
            img = fetch_city_image(name)
            weather["image_url"] = img["image_url"]
            weather["wiki_description"] = img["wiki_description"]
            # attach avg rating
            conn2 = get_db_connection()
            avg = conn2.execute("SELECT AVG(rating) as a, COUNT(*) as c FROM reviews WHERE city_name=?",
                                (name,)).fetchone()
            conn2.close()
            weather["avg_rating"] = round(avg["a"], 1) if avg["a"] else None
            weather["review_count"] = avg["c"]
            results.append(weather)
    return jsonify(results)

# ---------- REVIEW ROUTES ----------
@app.route("/get-reviews/<city_name>")
@login_required
def get_reviews(city_name):
    conn = get_db_connection()
    reviews = conn.execute("""
        SELECT r.id, r.rating, r.comment, r.created_at, r.updated_at, u.username, r.user_id
        FROM reviews r JOIN users u ON r.user_id = u.id
        WHERE r.city_name = ?
        ORDER BY r.created_at DESC
    """, (city_name,)).fetchall()
    avg_row = conn.execute(
        "SELECT AVG(rating) as avg_rating, COUNT(*) as count FROM reviews WHERE city_name=?",
        (city_name,)).fetchone()
    my_review = conn.execute(
        "SELECT rating, comment FROM reviews WHERE city_name=? AND user_id=?",
        (city_name, session["user_id"])).fetchone()
    conn.close()
    return jsonify({
        "reviews": [dict(r) for r in reviews],
        "avg_rating": round(avg_row["avg_rating"], 1) if avg_row["avg_rating"] else None,
        "count": avg_row["count"],
        "my_review": dict(my_review) if my_review else None
    })

@app.route("/add-review", methods=["POST"])
@login_required
def add_review():
    data = request.get_json()
    city = data.get("city", "").strip()
    rating = data.get("rating")
    comment = data.get("comment", "").strip()
    if not city or rating is None:
        return jsonify({"message": "City and rating are required."}), 400
    if not isinstance(rating, int) or not (1 <= rating <= 10):
        return jsonify({"message": "Rating must be 1–10."}), 400
    conn = get_db_connection()
    existing = conn.execute("SELECT id FROM reviews WHERE user_id=? AND city_name=?",
                            (session["user_id"], city)).fetchone()
    if existing:
        conn.execute("UPDATE reviews SET rating=?, comment=?, updated_at=? WHERE user_id=? AND city_name=?",
                     (rating, comment, datetime.now().isoformat(), session["user_id"], city))
        msg = "Review updated!"
    else:
        conn.execute("INSERT INTO reviews (user_id, city_name, rating, comment) VALUES (?,?,?,?)",
                     (session["user_id"], city, rating, comment))
        msg = "Review posted!"
    conn.commit()
    conn.close()
    return jsonify({"message": msg})

@app.route("/delete-review", methods=["POST"])
@login_required
def delete_review():
    data = request.get_json()
    conn = get_db_connection()
    conn.execute("DELETE FROM reviews WHERE city_name=? AND user_id=?",
                 (data["city"], session["user_id"]))
    conn.commit()
    conn.close()
    return jsonify({"message": "Review deleted."})

if __name__ == "__main__":
    init_db()
    app.run(debug=True)

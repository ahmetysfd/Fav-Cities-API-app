from flask import Flask, request, jsonify, render_template, session, redirect
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import requests
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = "skywatch_secret_key_2024_change_in_prod"

API_KEY = "3bac4e88f67a52186b7cbc5c22155ad3"

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

    conn.commit()
    conn.close()

# ---------- AUTH DECORATOR ----------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"message": "Unauthorized. Please log in."}), 401
        return f(*args, **kwargs)
    return decorated

# ---------- WEATHER FUNCTION ----------
def get_weather(city):
    city = city.title()
    url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={API_KEY}&units=metric"
    response = requests.get(url)
    data = response.json()

    if data.get("cod") != 200:
        return {"city": city, "error": True, "description": "City not found", "icon": ""}

    icon = data["weather"][0]["icon"]
    weather_main = data["weather"][0]["main"]

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
        "weather_main": weather_main,
        "icon": f"https://openweathermap.org/img/wn/{icon}@2x.png",
        "visibility": round(data.get("visibility", 0) / 1000, 1),
        "pressure": data["main"]["pressure"],
        "sunrise": datetime.utcfromtimestamp(data["sys"]["sunrise"]).strftime("%H:%M"),
        "sunset": datetime.utcfromtimestamp(data["sys"]["sunset"]).strftime("%H:%M"),
    }

# ---------- ROUTES ----------
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
    if not username.isalnum() and "_" not in username:
        return jsonify({"message": "Username can only contain letters, numbers, and underscores."}), 400
    if len(password) < 6:
        return jsonify({"message": "Password must be at least 6 characters."}), 400

    conn = get_db_connection()
    existing = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if existing:
        conn.close()
        return jsonify({"message": "Username already taken. Try another."}), 409

    hashed = generate_password_hash(password)
    conn.execute("INSERT INTO users (username, password) VALUES (?,?)", (username, hashed))
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
    user = conn.execute("SELECT created_at, last_login FROM users WHERE id=?",
                        (session["user_id"],)).fetchone()
    count = conn.execute("SELECT COUNT(*) as c FROM cities WHERE user_id=?",
                         (session["user_id"],)).fetchone()
    conn.close()
    return jsonify({
        "username": session["username"],
        "user_id": session["user_id"],
        "city_count": count["c"],
        "member_since": user["created_at"][:10] if user["created_at"] else "N/A",
    })

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
    existing = conn.execute("SELECT id FROM cities WHERE user_id=? AND city_name=?",
                            (user_id, weather["city"])).fetchone()
    if existing:
        conn.close()
        return jsonify({"message": f"{weather['city']} is already in your list."}), 409

    conn.execute("INSERT INTO cities (user_id, city_name) VALUES (?,?)",
                 (user_id, weather["city"]))
    conn.commit()
    conn.close()
    return jsonify({"message": "City added!", "weather": weather})

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
    weather_data = [get_weather(city["city_name"]) for city in cities]
    return jsonify(weather_data)

@app.route("/refresh-city", methods=["POST"])
@login_required
def refresh_city():
    data = request.get_json()
    weather = get_weather(data["city"])
    return jsonify(weather)

if __name__ == "__main__":
    init_db()
    app.run(debug=True)

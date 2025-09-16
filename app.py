from flask import Flask, redirect, url_for, session, request, render_template, jsonify
from authlib.integrations.flask_client import OAuth
import sqlite3
import requests
import os
from dotenv import load_dotenv
import re
import threading
import traceback


load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

# --- OAuth Google ---
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

# --- DB ---
def init_db():
    conn = sqlite3.connect("chat_history.db")
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT,
            role TEXT,
            content TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- Sauvegarde asynchrone ---
def save_message_async(user_email, role, content):
    def save():
        conn = sqlite3.connect("chat_history.db")
        c = conn.cursor()
        c.execute(
            "INSERT INTO messages (user_email, role, content) VALUES (?, ?, ?)",
            (user_email, role, content)
        )
        conn.commit()
        conn.close()
    threading.Thread(target=save).start()

# --- Format IA response ---
def format_ai_response(text):
    text = re.sub(r'◁think▷.*?◁/think▷', '', text, flags=re.DOTALL)
    
    replacements = {
        "Objectif": "🎯 <b>Objectif</b>",
        "Action": "✅ <b>Action</b>",
        "Astuce": "💡 <b>Astuce</b>",
        "Important": "📝 <b>Important</b>"
    }
    for k, v in replacements.items():
        text = re.sub(k, v, text)

    keywords_red = ["rappel", "attention", "note"]
    keywords_blue = ["conseil", "tip"]
    keywords_green = ["exemple"]

    for kw in keywords_red:
        text = re.sub(rf'\b{kw}\b', f'<span style="color:#d9534f;font-weight:bold;">{kw}</span>', text, flags=re.IGNORECASE)
    for kw in keywords_blue:
        text = re.sub(rf'\b{kw}\b', f'<span style="color:#0275d8;font-weight:bold;">{kw}</span>', text, flags=re.IGNORECASE)
    for kw in keywords_green:
        text = re.sub(rf'\b{kw}\b', f'<span style="color:#5cb85c;font-weight:bold;">{kw}</span>', text, flags=re.IGNORECASE)

    return text.replace("\n", "<br>").strip()

# --- Routes ---
@app.route('/')
def index():
    if "user" in session:
        return redirect(url_for("chat"))
    return render_template("login.html")  # page avec bouton "Se connecter avec Google"

# --- Login Google ---
@app.route('/login')
def login():
    redirect_uri = url_for('authorize', _external=True)
    return google.authorize_redirect(redirect_uri, prompt="consent")

@app.route('/authorize')
def authorize():
    try:
        # Récupère le token d'accès
        token = google.authorize_access_token()

        # Récupère les infos utilisateur directement depuis Google
        resp = requests.get(
            'https://openidconnect.googleapis.com/v1/userinfo',
            headers={'Authorization': f"Bearer {token['access_token']}"}
        )
        userinfo = resp.json()

        # Debug: affiche les infos récupérées
        print("Userinfo:", userinfo)

        # Stocke les infos dans la session
        session['user'] = {
            'email': userinfo.get('email'),
            'name': userinfo.get('name'),
            'picture': userinfo.get('picture')
        }

        return redirect(url_for("chat"))

    except Exception as e:
        import traceback
        print("Erreur OAuth:")
        traceback.print_exc()
        return f"Échec de l'authentification Google. Détails : {e}"

from flask import make_response
@app.route('/logout')
def logout():
    session.clear()  # supprime toute la session
    resp = make_response(redirect("/"))
    resp.set_cookie('session', '', expires=0)  # supprime le cookie de session côté client
    return resp


@app.route('/chat')
def chat():
    if "user" not in session:
        return redirect("/")
    return render_template("chat.html", email=session['user']['email'])

@app.route('/get_history')
def get_history():
    user_email = session['user']['email']
    conn = sqlite3.connect("chat_history.db")
    c = conn.cursor()
    c.execute("SELECT role, content FROM messages WHERE user_email=? ORDER BY id DESC LIMIT 50", (user_email,))
    history = [{"role": role, "content": content} for role, content in c.fetchall()]
    conn.close()
    return jsonify({"history": history})

@app.route('/send_message', methods=['POST'])
def send_message():
    if "user" not in session:
        return jsonify({"error": "Non authentifié"}), 401

    user_email = session['user']['email']
    user_text = request.json.get("message")
    save_message_async(user_email, "user", user_text)

    # Historique pour IA
    conn = sqlite3.connect("chat_history.db")
    c = conn.cursor()
    c.execute("SELECT role, content FROM messages WHERE user_email=? ORDER BY id DESC LIMIT 10", (user_email,))
    history = c.fetchall()
    conn.close()

    messages_for_api = []
    for role, content in reversed(history):
        messages_for_api.append({"role": role, "content": [{"type": "text", "text": content}]})
    messages_for_api.append({"role": "user", "content": [{"type": "text", "text": user_text}]})

    API_KEY = os.getenv("OPENROUTER_API_KEY")
    MODEL_ID = os.getenv("MODEL_ID")
    data = {
        "model": MODEL_ID,
        "messages": messages_for_api,
        "max_tokens": 1000
    }
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    try:
        response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data, timeout=20)
        response.raise_for_status()
        result = response.json()
        reply_raw = result["choices"][0]["message"]["content"]
        reply = format_ai_response(reply_raw)
        save_message_async(user_email, "assistant", reply)
        return jsonify({"reply": reply})
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)

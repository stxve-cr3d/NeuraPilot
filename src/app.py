import os
from flask import Flask, request, jsonify, render_template
from openai import OpenAI
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static")
)

load_dotenv()
client = OpenAI()

SYSTEM_PROMPT = """
Du bist BusinessPilot AI, ein professioneller Sales- & Support-Chatbot.
Dein Ziel:
- Besucher freundlich empfangen
- Bedarf verstehen
- qualifizieren
- zu einer Demo oder Terminbuchung führen

Regeln:
- Kurz & klar antworten
- Maximal eine Frage pro Nachricht
- Kein Druck, kein Spam
- Wenn Interesse erkennbar → Demo anbieten
"""

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.json.get("message")

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ]
    )

    reply = response.choices[0].message.content
    return jsonify({"reply": reply})

if __name__ == "__main__":
    app.run()
from flask import Flask
from threading import Thread
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "✅ I'm alive!"

def run():
    port = int(os.environ.get("PORT", 8080))  # Render가 자동 지정한 포트를 사용
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

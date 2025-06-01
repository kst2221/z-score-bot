from flask import Flask
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "✅ I'm alive!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    run()  # ← Render가 이 entrypoint를 감지함

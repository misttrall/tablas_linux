from flask import Flask, render_template
from routes.web_routes import web_routes

app = Flask(__name__)

app.register_blueprint(web_routes, url_prefix="/api")

@app.route("/")
def home():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True)
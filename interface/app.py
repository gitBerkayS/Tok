import random

from flask import Flask, render_template, jsonify

app = Flask(__name__)

REFERENCE_SCALE = 50000  # token budget the UI bar is measured against


def get_token_count():
    """Return the predicted token count as an int.

    TEAMMATES: replace the body of this function with the real model call
    (e.g. import their predictor and return its output). The frontend does not
    need to change as long as this returns an int.
    """
    # MOCK: random so the mascot, bar colour and history graph visibly react.
    return random.randint(300, 55000)


@app.route("/")
def home():
    return render_template("index.html", reference_scale=REFERENCE_SCALE)


@app.route("/api/usage")
def get_usage():
    return jsonify(tokens=get_token_count(), scale=REFERENCE_SCALE)


if __name__ == "__main__":
    app.run(debug=True)

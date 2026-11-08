"""SolCare 보호자 앱 (Flask + HTML 템플릿).

실행:  python app/app.py        ->  http://127.0.0.1:5000
DB:    python server/db/import_session.py solcare.db <vitals.csv> <events.csv> <meta.json>
"""
from flask import Flask, abort, render_template

import report

app = Flask(__name__)


@app.context_processor
def inject_common():
    return {"nav": [("/", "오늘 아침"), ("/alerts", "알림"), ("/history", "기록")]}


def _need_db():
    return None if report.db_exists() else render_template("nodb.html", path=report.db_path()), 503


@app.route("/")
def home():
    if not report.db_exists():
        return _need_db()
    sessions = report.list_sessions()
    if not sessions:
        return render_template("empty.html")
    return render_template("home.html", r=report.build_report(sessions[0]["session_id"]), active="/")


@app.route("/alerts")
def alerts():
    if not report.db_exists():
        return _need_db()
    sessions = report.list_sessions()
    if not sessions:
        return render_template("empty.html")
    return render_template("alerts.html", r=report.build_report(sessions[0]["session_id"]), active="/alerts")


@app.route("/history")
def history():
    if not report.db_exists():
        return _need_db()
    return render_template("history.html", sessions=report.list_sessions(), active="/history")


@app.route("/report/<session_id>")
def detail(session_id):
    if not report.db_exists():
        return _need_db()
    r = report.build_report(session_id)
    if r is None:
        abort(404)
    return render_template("home.html", r=r, active="/history")


if __name__ == "__main__":
    app.run(debug=True)

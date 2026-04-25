from flask import Blueprint, jsonify, send_from_directory
from services.mock_etl import run_etl_process
from services.mock_reports import generate_report_pdf
from services.export_service import export_excel, export_pdf
import os

web_routes = Blueprint("web_routes", __name__)

@web_routes.route("/run-etl", methods=["POST"])
def run_etl():
    logs = run_etl_process()
    return jsonify({
        "status": "success",
        "logs": logs,
        "metrics": {
            "records_processed": 15234,
            "errors": 3,
            "duration_sec": 2.8
        }
    })


@web_routes.route("/export/pdf")
def pdf():
    file = export_pdf()
    return jsonify({"file": file})


@web_routes.route("/export/excel")
def excel():
    file = export_excel()
    return jsonify({"file": file})


@web_routes.route("/download/<filename>")
def download(filename):
    return send_from_directory(
    os.path.join(os.getcwd(), "reports"),
    filename,
    as_attachment=True
)
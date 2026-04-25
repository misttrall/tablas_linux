async function generateReport() {
    document.getElementById("logs").innerText = "Generando reporte...\n";

    const res = await fetch("/api/run-report", {
        method: "POST"
    });

    const data = await res.json();

    // mostrar logs simulados
    for (let log of data.logs) {
        document.getElementById("logs").innerText += log + "\n";
        await new Promise(r => setTimeout(r, 250));
    }

    document.getElementById("reportInfo").innerText =
        "Reporte generado: " + data.report_id;

    document.getElementById("file").innerHTML =
        `<a href="/api/download-report/${data.file}" target="_blank">
            📥 Descargar PDF
        </a>`;
}
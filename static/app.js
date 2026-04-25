let chart;

function initChart() {
    const ctx = document.getElementById("chart");

    chart = new Chart(ctx, {
        type: "bar",
        data: {
            labels: ["Procesados", "Errores"],
            datasets: [{
                data: [0, 0]
            }]
        }
    });
}

async function runETL() {
    const res = await fetch("/api/run-etl", { method: "POST" });
    const data = await res.json();

    document.getElementById("kpiRecords").innerText =
        data.metrics.records_processed;

    document.getElementById("kpiErrors").innerText =
        data.metrics.errors;

    document.getElementById("kpiTime").innerText =
        data.metrics.duration_sec + "s";

    chart.data.datasets[0].data = [
        data.metrics.records_processed,
        data.metrics.errors
    ];
    chart.update();

    showLogs(data.logs);

    loadTable();
}

function loadTable() {
    const data = [
        ["A", 120, 30, "OK"],
        ["B", 45, 12, "CRITICO"],
        ["C", 78, 50, "OK"],
        ["D", 200, 90, "OK"]
    ];

    const table = document.getElementById("table");
    table.innerHTML = "";

    data.forEach(r => {
        table.innerHTML += `
            <tr>
                <td>${r[0]}</td>
                <td>${r[1]}</td>
                <td>${r[2]}</td>
                <td>${r[3]}</td>
            </tr>
        `;
    });
}

async function exportExcel() {
    const res = await fetch("/api/export/excel");
    const data = await res.json();
    window.open("/api/download/" + data.file);
}

async function exportPDF() {
    const res = await fetch("/api/export/pdf");
    const data = await res.json();
    window.open("/api/download/" + data.file);
}

function showLogs(lines) {
    document.getElementById("logs").innerText = lines.join("\n");
}

window.onload = () => {
    initChart();
    loadTable();
};
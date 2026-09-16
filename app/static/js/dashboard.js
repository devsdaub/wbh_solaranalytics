const stil = getComputedStyle(document.documentElement);
const FARBE_PRODUKTION = stil.getPropertyValue("--color-data").trim();
const FARBE_EINSTRAHLUNG = stil.getPropertyValue("--color-data-2").trim();
const FARBE_DRITTE = stil.getPropertyValue("--color-data-3").trim();

let zeitreihe = null;
let trends = null;

async function ladeJson(pfad) {
    const antwort = await fetch(pfad);
    if (!antwort.ok) {
        throw new Error(`Datenabruf fehlgeschlagen: ${antwort.status}`);
    }
    return antwort.json();
}

function zeichneZeitreihe(daten) {
    zeitreihe = new Chart(document.getElementById("chart-zeitreihe"), {
        type: "line",
        data: {
            labels: daten.labels,
            datasets: [
                {
                    label: "Produktion kWh",
                    data: daten.produktion,
                    borderColor: FARBE_PRODUKTION,
                    backgroundColor: FARBE_PRODUKTION,
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.2,
                },
                {
                    label: "Einstrahlung kWh/m²",
                    data: daten.einstrahlung,
                    borderColor: FARBE_EINSTRAHLUNG,
                    backgroundColor: FARBE_EINSTRAHLUNG,
                    borderWidth: 1,
                    pointRadius: 0,
                    tension: 0.2,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            scales: {
                y: { beginAtZero: true, title: { display: true, text: "kWh" } },
                x: { ticks: { maxTicksLimit: 12 } },
            },
        },
    });
}

async function wechsleZeitraum(tage, knopf) {
    document.querySelectorAll(".zeitraum-knopf").forEach((element) => {
        element.classList.remove("aktiv");
    });
    knopf.classList.add("aktiv");
    document.getElementById("zeitraum-titel").textContent = knopf.dataset.titel;

    const daten = await ladeJson(`/api/data/daily?days=${tage}`);
    zeitreihe.data.labels = daten.labels;
    zeitreihe.data.datasets[0].data = daten.produktion;
    zeitreihe.data.datasets[1].data = daten.einstrahlung;
    zeitreihe.update();
}

function zeichneStreuung(daten) {
    new Chart(document.getElementById("chart-streuung"), {
        type: "scatter",
        data: {
            datasets: [
                {
                    label: "Tageswerte",
                    data: daten.punkte,
                    backgroundColor: FARBE_PRODUKTION,
                    pointRadius: 3,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (punkt) => {
                            const wert = punkt.raw;
                            return `${wert.datum}: ${wert.y} kWh bei ${wert.x.toFixed(2)} kWh/m²`;
                        },
                    },
                },
            },
            scales: {
                x: { beginAtZero: true, title: { display: true, text: "Einstrahlung kWh/m²" } },
                y: { beginAtZero: true, title: { display: true, text: "Produktion kWh" } },
            },
        },
    });
}

function zeichneMonate(daten) {
    const stufen = [
        stil.getPropertyValue("--hm-1").trim(),
        stil.getPropertyValue("--hm-2").trim(),
        stil.getPropertyValue("--hm-3").trim(),
        stil.getPropertyValue("--hm-4").trim(),
        stil.getPropertyValue("--hm-5").trim(),
    ];
    const jahresfarben = [FARBE_PRODUKTION, FARBE_EINSTRAHLUNG, FARBE_DRITTE];
    const einJahr = daten.reihen.length === 1;

    const datensaetze = daten.reihen.map((reihe, i) => {
        let farbe = jahresfarben[i % jahresfarben.length];

        if (einJahr) {
            const gueltig = reihe.werte.filter((wert) => wert !== null);
            const hoechst = gueltig.length ? Math.max(...gueltig) : 0;
            farbe = reihe.werte.map((wert) => {
                if (wert === null || hoechst <= 0) return stufen[0];
                return stufen[Math.min(Math.floor((wert / hoechst) * 5), 4)];
            });
        }

        return {
            label: String(reihe.jahr),
            data: reihe.werte,
            backgroundColor: farbe,
            borderRadius: 4,
            tage: reihe.tage,
        };
    });

    new Chart(document.getElementById("chart-monate"), {
        type: "bar",
        data: { labels: daten.labels, datasets: datensaetze },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: !einJahr },
                tooltip: {
                    callbacks: {
                        afterLabel: (punkt) => {
                            const anzahl = punkt.dataset.tage[punkt.dataIndex];
                            return anzahl ? `${anzahl} Messtage` : "";
                        },
                    },
                },
            },
            scales: {
                y: { beginAtZero: true, title: { display: true, text: "kWh" } },
            },
        },
    });
}

const FARBEN_FAKTOR = {
    temperatur: "#ef4444",
    bewoelkung: FARBE_DRITTE,
    staub: FARBE_EINSTRAHLUNG,
};

function zeichneTrends(daten, faktor) {
    const vergleich = daten.reihen[faktor];
    const farbe = FARBEN_FAKTOR[faktor];

    trends = new Chart(document.getElementById("chart-trends"), {
        type: "line",
        data: {
            labels: daten.labels,
            datasets: [
                {
                    label: "Produktion kWh/Tag",
                    data: daten.reihen.produktion.werte,
                    borderColor: FARBE_PRODUKTION,
                    backgroundColor: FARBE_PRODUKTION,
                    borderWidth: 2.5,
                    pointRadius: 2,
                    tension: 0.3,
                    yAxisID: "y",
                },
                {
                    label: `${vergleich.titel} ${vergleich.einheit}`.trim(),
                    data: vergleich.werte,
                    borderColor: farbe,
                    backgroundColor: farbe,
                    borderWidth: 1.5,
                    pointRadius: 2,
                    tension: 0.3,
                    yAxisID: "y2",
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            scales: {
                y: {
                    position: "left",
                    beginAtZero: true,
                    title: { display: true, text: "Produktion kWh/Tag" },
                },
                y2: {
                    position: "right",
                    title: { display: true, text: vergleich.einheit || vergleich.titel },
                    grid: { drawOnChartArea: false },
                },
                x: { ticks: { maxTicksLimit: 10 } },
            },
        },
    });
}

function wechsleFaktor(daten, faktor, knopf) {
    document.querySelectorAll(".faktor-knopf").forEach((element) => {
        element.classList.remove("aktiv");
    });
    knopf.classList.add("aktiv");

    const vergleich = daten.reihen[faktor];
    trends.data.datasets[1].label = `${vergleich.titel} ${vergleich.einheit}`.trim();
    trends.data.datasets[1].data = vergleich.werte;
    trends.data.datasets[1].borderColor = FARBEN_FAKTOR[faktor];
    trends.data.datasets[1].backgroundColor = FARBEN_FAKTOR[faktor];
    trends.options.scales.y2.title.text = vergleich.einheit || vergleich.titel;
    trends.update();
}

async function start() {
    let trendDaten = null;

    try {
        zeichneZeitreihe(await ladeJson("/api/data/daily?days=90"));
        zeichneStreuung(await ladeJson("/api/data/scatter"));
        zeichneMonate(await ladeJson("/api/data/monthly"));

        trendDaten = await ladeJson("/api/data/trends");
        zeichneTrends(trendDaten, "temperatur");
    } catch (fehler) {
        console.error(fehler);
        return;
    }

    document.querySelectorAll(".zeitraum-knopf").forEach((knopf) => {
        knopf.addEventListener("click", () => {
            wechsleZeitraum(Number(knopf.dataset.tage), knopf).catch(console.error);
        });
    });

    document.querySelectorAll(".faktor-knopf").forEach((knopf) => {
        knopf.addEventListener("click", () => {
            wechsleFaktor(trendDaten, knopf.dataset.faktor, knopf);
        });
    });
}

start();
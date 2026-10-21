const stil = getComputedStyle(document.documentElement);
const FARBE = {
    gruen: stil.getPropertyValue("--color-data").trim(),
    dunkel: stil.getPropertyValue("--color-heading").trim(),
    band: "rgba(27, 58, 92, 0.13)",
    blau: stil.getPropertyValue("--color-data-2").trim(),
    text: stil.getPropertyValue("--color-text").trim(),
};
const WETTERNAME = { sonne: "sonnig", heiter: "heiter", wolkig: "wolkig", bedeckt: "bedeckt", regen: "Regen" };
const MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];

// Jeder Wert, den die Pipeline abruft, mit den Merkmalen, die das Modell daraus bildet
const QUELLEN = {
    wetter: "Open-Meteo Wetter, ICON-D2",
    satellit: "Satellit SARAH-3",
    luft: "Open-Meteo Luftqualität, CAMS",
    berechnet: "aus Datum und Breitengrad berechnet",
};
const WERTE = [
    { name: "Einstrahlung, vom Satelliten gemessen", quelle: "satellit", merkmale: ["gti_satellit_kwh_m2"] },
    { name: "Einstrahlung auf die Module", quelle: "wetter", merkmale: ["gti_kwh_m2"] },
    { name: "Sonnenstunden", quelle: "wetter", merkmale: ["sonnenstunden"] },
    { name: "Bewölkung gesamt", quelle: "wetter", merkmale: ["wolken_mittel", "wolken_streuung"] },
    { name: "tiefe Wolken", quelle: "wetter", merkmale: ["wolken_tief"] },
    { name: "mittelhohe Wolken", quelle: "wetter", merkmale: ["wolken_mittelhoch"] },
    { name: "hohe Wolken", quelle: "wetter", merkmale: ["wolken_hoch"] },
    { name: "Temperatur", quelle: "wetter", merkmale: ["temp_mittel", "temp_max"] },
    { name: "Aerosole, also Dunst", quelle: "luft", merkmale: ["aerosol_mittel"] },
    { name: "Feinstaub PM10", quelle: "luft", merkmale: ["pm10_mittel"] },
    { name: "Saharastaub", quelle: "luft", merkmale: ["staub_max", "staub_mittel"] },
    { name: "Sonnenhöhe am Mittag", quelle: "berechnet", merkmale: ["mittagshoehe_grad"] },
    { name: "Tageslänge", quelle: "berechnet", merkmale: ["tageslaenge_h"] },
    { name: "Jahreszeit", quelle: "berechnet", merkmale: ["jahrestag_sin", "jahrestag_cos"] },
];

Chart.defaults.font.family = stil.getPropertyValue("--font-display").trim() || "system-ui";
Chart.defaults.color = stil.getPropertyValue("--color-text-muted").trim();

let D = null;

const fmt = (x, n = 2) => (x === null || x === undefined || Number.isNaN(x)) ? "n. v." : x.toFixed(n).replace(".", ",");
const prozent = (x) => x <= 0 ? "0 %" : `${fmt(x, x >= 1 ? 1 : x >= 0.1 ? 2 : 3)} %`;
const tagKurz = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" });
const zeitpunkt = (iso) => {
    if (!iso) {
        return "noch nie";
    }
    const d = new Date(iso);
    return `am ${d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" })} um ${d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })} Uhr`;
};
const achsen = () => ({ ticks: { font: { size: 11 } }, grid: { color: "#e8edf3" } });

// Schreibt den Wert ans Ende jedes Balkens, Texte kommen aus options.plugins.wertBeschriftung.texte
const wertBeschriftung = {
    id: "wertBeschriftung",
    afterDatasetsDraw(diagramm, argumente, optionen) {
        const { ctx, chartArea } = diagramm;
        ctx.save();
        ctx.font = `600 12px ${Chart.defaults.font.family}`;
        ctx.fillStyle = FARBE.text;
        ctx.textBaseline = "middle";
        diagramm.getDatasetMeta(0).data.forEach((balken, i) => {
            const x = Number.isFinite(balken.x) && balken.x > chartArea.left ? balken.x : chartArea.left;
            ctx.fillText(optionen.texte[i], x + 8, balken.y);
        });
        ctx.restore();
    },
};

async function ladeJson(pfad) {
    const antwort = await fetch(pfad);
    if (!antwort.ok) {
        throw new Error(`Datenabruf fehlgeschlagen: ${pfad} ${antwort.status}`);
    }
    return antwort.json();
}

function chart(id, konfiguration) {
    const element = document.getElementById(id);
    const alt = Chart.getChart(element);
    if (alt) {
        alt.destroy();
    }
    return new Chart(element, konfiguration);
}

function teil(html, nach) {
    return { html, nach: nach ? [nach] : [] };
}

function zusammen(...teile) {
    return { html: teile.map((t) => t.html).join(""), nach: teile.flatMap((t) => t.nach) };
}

function raster(...teile) {
    const z = zusammen(...teile);
    return { html: `<div class="raster">${z.html}</div>`, nach: z.nach };
}

function kennzahl(wert, einheit, label) {
    return `<div class="stat"><span class="stat-value">${wert}${einheit ? ` <small>${einheit}</small>` : ""}</span><span class="stat-label">${label}</span></div>`;
}

// --- Kopf: vier Kacheln und Wetterbericht ---------------------------------------------------

function kacheln() {
    const morgen = D.prognose.tage.find((t) => t.vorlauf === 1);
    const stichtag = new Date(D.prognose.stichtag + "T12:00:00");
    const letzte7 = D.verlauf.tage.filter((t) => t.datum < D.prognose.stichtag && t.ist !== null && t.p1 !== null).slice(-7);
    const woche = letzte7.reduce((s, t) => s + t.ist, 0);
    const wocheVorhergesagt = letzte7.reduce((s, t) => s + t.p1, 0);
    // Gemessen gegen die Prognose vom Vortag, über alle Tage des laufenden Monats, heute mit Live-Wert
    const praefix = D.prognose.stichtag.slice(0, 8);
    const tage = D.verlauf.tage.filter((t) => t.datum.startsWith(praefix) && t.ist !== null && t.p1 !== null);
    const heute = D.prognose.tage.find((t) => t.vorlauf === 0);
    const live = D.realtime.status === "ok" && heute;
    const monat = tage.reduce((s, t) => s + t.ist, 0) + (live ? D.realtime.heute_kwh : 0);
    const vorhergesagt = tage.reduce((s, t) => s + t.p1, 0) + (live ? heute.prognose : 0);
    return teil(`<section class="stats">
        ${kennzahl(fmt(morgen.prognose, 1), "kWh", `Morgen, ${tagKurz(morgen.datum)}`)}
        ${kennzahl(fmt(woche, 1), "kWh", `Letzte 7 Tage, vorhergesagt waren ${fmt(wocheVorhergesagt, 1)} kWh`)}
        ${kennzahl(fmt(monat, 1), "kWh", `${MONATE[stichtag.getMonth()]} bisher, vorhergesagt waren ${fmt(vorhergesagt, 1)} kWh`)}
        ${kennzahl("8 von 10", "", "Tagen lag die Messung in der Spanne")}
    </section>`);
}

// Symbol nach Sonnenanteil und Regen, nicht nach dem WMO-Tagescode, der das schlechteste Wetter des Tages meldet
function wetterIcon(t) {
    const regen = t.regen_mm || 0;
    const icon = {
        sonne: "clear-day",
        heiter: "mostly-clear-day",
        wolkig: regen >= 1 ? "partly-cloudy-day-rain" : "partly-cloudy-day",
        bedeckt: regen >= 1 ? "overcast-day-drizzle" : "overcast-day",
        regen: "overcast-day-rain",
    }[t.symbol];
    const text = t.symbol === "wolkig" && regen >= 1 ? "wolkig, Schauer" : t.symbol === "bedeckt" && regen >= 1 ? "bedeckt, Niesel" : WETTERNAME[t.symbol];
    return { icon, text };
}

function wetterbericht() {
    const p = D.prognose;
    const maxKwh = Math.max(...p.tage.map((t) => t.oben || 0), 1) * 1.08;
    const pro = (x) => (100 * (x || 0) / maxKwh).toFixed(1);
    const tage = p.tage.map((t) => {
        const w = wetterIcon(t);
        return `
        <div class="tag${t.vorlauf === 0 ? " heute" : ""}">
            <div><div class="tag-kopf">${t.name}</div><div class="tag-datum">${tagKurz(t.datum)}</div></div>
            <img src="/static/icons/meteocons/${w.icon}.svg" width="64" height="64" alt="${w.text}">
            <div class="tag-wetter">${w.text}<br>${fmt(t.sonne_h, 1)} h Sonne<br>${fmt(t.temp_max, 0)} °C · ${fmt(t.gti, 1)} kWh/m²</div>
            <div class="saeule"><div class="balken" style="height:${pro(t.prognose)}%"></div><div class="band" style="bottom:${pro(t.unten)}%;height:${pro(t.oben - t.unten)}%"></div></div>
            <div class="tag-kwh">${fmt(t.prognose, 1)} <small>kWh</small></div>
            <div class="tag-band">${fmt(t.unten, 1)} bis ${fmt(t.oben, 1)}</div>
        </div>`;
    }).join("");
    return teil(`<section class="card">
        <div class="card-kopf"><h2>Wetterbericht und erwarteter Ertrag, nächste 7 Tage</h2>
            <div class="legende"><span><i style="background:var(--color-data)"></i>Prognose</span><span><i style="background:var(--color-heading)"></i>Spanne, in der 8 von 10 Tagen landen</span></div>
        </div>
        <div class="vorschau-wrap"><div class="vorschau">${tage}</div></div>
    </section>`);
}

// --- Prognose gegen Messung, Abweichung, Streuung ---------------------------------------------

function messung() {
    const zustand = { tage: 60, vorlauf: 1 };
    const zeichnen = () => {
        const v = D.verlauf.tage.slice(-zustand.tage);
        const h = zustand.vorlauf;
        const p = v.map((z) => z[`p${h}`]);
        document.getElementById("verlauf-titel").textContent = `Prognose gegen Messung, letzte ${zustand.tage} Tage, ${h === 1 ? "Prognose vom Vortag" : `Prognose von ${h} Tagen vorher`}`;
        chart("chart-verlauf", {
            data: {
                labels: v.map((z) => tagKurz(z.datum)),
                datasets: [
                    { type: "line", label: "Spanne oben", data: v.map((z) => z[`o${h}`]), borderWidth: 0, pointRadius: 0, fill: "+1", backgroundColor: FARBE.band, order: 3 },
                    { type: "line", label: "Spanne unten", data: v.map((z) => z[`u${h}`]), borderWidth: 0, pointRadius: 0, fill: false, order: 3 },
                    { type: "line", label: "Prognose", data: p, borderColor: FARBE.dunkel, backgroundColor: FARBE.dunkel, borderWidth: 2, pointRadius: v.length > 70 ? 0 : 2.5, tension: 0.15, order: 1 },
                    { type: "bar", label: "Gemessen", data: v.map((z) => z.ist), backgroundColor: FARBE.gruen, borderRadius: 2, order: 2 },
                ],
            },
            options: {
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                plugins: {
                    legend: { labels: { filter: (i) => !i.text.startsWith("Spanne"), boxWidth: 12 } },
                    tooltip: { callbacks: { label: (c) => c.dataset.label.startsWith("Spanne") ? null : `${c.dataset.label}: ${fmt(c.parsed.y)} kWh` } },
                },
                scales: { x: { ...achsen(), ticks: { maxTicksLimit: 12 }, grid: { display: false } }, y: { ...achsen(), beginAtZero: true, title: { display: true, text: "kWh je Tag" } } },
            },
        });
        const ab = v.map((z, i) => (z.ist === null || p[i] === null) ? null : p[i] - z.ist);
        chart("chart-abweichung", {
            type: "bar",
            data: { labels: v.map((z) => tagKurz(z.datum)), datasets: [{ label: "Prognose minus Messung", data: ab, borderRadius: 2, backgroundColor: ab.map((a) => (a !== null && a >= 0) ? FARBE.dunkel : FARBE.blau) }] },
            options: {
                maintainAspectRatio: false,
                plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${c.parsed.y >= 0 ? "zu hoch um " : "zu niedrig um "}${fmt(Math.abs(c.parsed.y))} kWh` } } },
                scales: { x: { ...achsen(), ticks: { maxTicksLimit: 8 }, grid: { display: false } }, y: { ...achsen(), title: { display: true, text: "kWh" } } },
            },
        });
        const punkte = v.filter((z, i) => z.ist !== null && p[i] !== null).map((z) => ({ x: z.ist, y: z[`p${h}`], datum: z.datum }));
        const grenze = Math.ceil(Math.max(...punkte.map((q) => Math.max(q.x, q.y)), 1));
        chart("chart-streuung-prognose", {
            data: { datasets: [
                { type: "scatter", label: "Tage", data: punkte, backgroundColor: FARBE.gruen, pointRadius: 3.5 },
                { type: "line", label: "genau getroffen", data: [{ x: 0, y: 0 }, { x: grenze, y: grenze }], borderColor: FARBE.dunkel, borderWidth: 1, borderDash: [5, 4], pointRadius: 0 },
            ] },
            options: {
                maintainAspectRatio: false,
                plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => c.raw.datum ? `${tagKurz(c.raw.datum)}: gemessen ${fmt(c.raw.x)}, Prognose ${fmt(c.raw.y)} kWh` : null } } },
                scales: { x: { ...achsen(), type: "linear", min: 0, max: grenze, title: { display: true, text: "gemessen, kWh" } }, y: { ...achsen(), min: 0, max: grenze, title: { display: true, text: "Prognose, kWh" } } },
            },
        });
    };
    const verlauf = teil(`<section class="card">
        <div class="card-kopf"><h2 id="verlauf-titel">Prognose gegen Messung</h2><div class="knopfleiste" id="verlauf-knoepfe">
            <button class="zeitraum-knopf" data-tage="30">30 T</button><button class="zeitraum-knopf aktiv" data-tage="60">60 T</button><button class="zeitraum-knopf" data-tage="120">120 T</button><button class="zeitraum-knopf" data-tage="180">180 T</button>
            <span class="knopf-trenner"></span>
            <button class="zeitraum-knopf aktiv" data-vorlauf="1">vom Vortag</button><button class="zeitraum-knopf" data-vorlauf="3">3 Tage vorher</button><button class="zeitraum-knopf" data-vorlauf="6">6 Tage vorher</button>
        </div></div>
        <div class="chart-box"><canvas id="chart-verlauf"></canvas></div>
    </section>`, () => {
        document.getElementById("verlauf-knoepfe").addEventListener("click", (ereignis) => {
            const knopf = ereignis.target.closest(".zeitraum-knopf");
            if (!knopf) {
                return;
            }
            const gruppe = knopf.dataset.tage ? "tage" : "vorlauf";
            zustand[gruppe] = Number(knopf.dataset[gruppe]);
            document.querySelectorAll(`#verlauf-knoepfe .zeitraum-knopf[data-${gruppe}]`).forEach((b) => b.classList.toggle("aktiv", b === knopf));
            zeichnen();
        });
        zeichnen();
    });
    const klein = raster(
        teil(`<section class="card">
            <div class="card-kopf"><h2>Abweichung je Tag</h2><div class="legende"><span><i style="background:var(--color-heading)"></i>Prognose zu hoch</span><span><i style="background:var(--color-data-2)"></i>zu niedrig</span></div></div>
            <div class="chart-box-klein"><canvas id="chart-abweichung"></canvas></div></section>`),
        teil(`<section class="card">
            <div class="card-kopf"><h2>Prognose über Messung</h2><div class="legende"><span><i style="background:var(--color-data)"></i>ein Tag</span><span><i style="background:var(--color-heading)"></i>Linie: genau getroffen</span></div></div>
            <div class="chart-box-klein"><canvas id="chart-streuung-prognose"></canvas></div></section>`),
    );
    return zusammen(verlauf, klein);
}

// --- Verfahren im Vergleich ---------------------------------------------------------------------

function verfahren() {
    const e = D.ergebnisse;
    const lage = e.lagen.vorhersage;
    // die dunkle Markierung folgt dem Verfahren, das der letzte Analyselauf eingesetzt hat
    const eingesetzt = e.eingesetzt.verfahren;
    const lernen = ["random_forest_nachgefuehrt", "xgboost_nachgefuehrt", "lineare_regression_nachgefuehrt"];
    const auswahl = [
        ["faustregel_nachgefuehrt", "Faustregel"],
        ["random_forest_nachgefuehrt", "Random Forest"],
        ["xgboost_nachgefuehrt", "XGBoost"],
        ["lineare_regression_nachgefuehrt", "Lineare Regression"],
        ["persistenz", "Wert vom Vortag"],
    ].map(([s, label]) => ({
        label, art: s === eingesetzt ? "eingesetzt" : lernen.includes(s) ? "lernen" : "vergleich",
        mae: lage.verfahren[s].S2.mae, nmae: lage.verfahren[s].S2.nmae_prozent,
    })).sort((a, b) => a.mae - b.mae);
    const farbe = { eingesetzt: FARBE.dunkel, lernen: FARBE.gruen, vergleich: FARBE.blau };
    return teil(`<section class="card">
        <div class="card-kopf"><h2>So weit liegen die Verfahren bei der Prognose für morgen im Mittel daneben</h2>
            <div class="legende"><span><i style="background:var(--color-heading)"></i>eingesetzt</span><span><i style="background:var(--color-data)"></i>Lernverfahren</span><span><i style="background:var(--color-data-2)"></i>zum Vergleich</span></div>
        </div>
        <div class="chart-box-klein"><canvas id="chart-verfahren"></canvas></div>
    </section>`, () => {
        chart("chart-verfahren", {
            type: "bar",
            data: { labels: auswahl.map((a) => a.label), datasets: [{ data: auswahl.map((a) => a.mae), backgroundColor: auswahl.map((a) => farbe[a.art]), borderRadius: 3, barPercentage: 0.7 }] },
            options: {
                indexAxis: "y",
                maintainAspectRatio: false,
                layout: { padding: { right: 16 } },
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: {
                        label: (c) => `im Mittel ${fmt(c.parsed.x, 2)} kWh daneben, ${fmt(auswahl[c.dataIndex].nmae, 0)} % eines mittleren Tages`,
                        afterLabel: (c) => auswahl[c.dataIndex].art === "vergleich" ? "nimmt einfach den gemessenen Ertrag von gestern" : "mit Nachführung an den Ertrag der letzten Tage",
                    } },
                    wertBeschriftung: { texte: auswahl.map((a) => `± ${fmt(a.mae, 2)} kWh · ${fmt(a.nmae, 0)} % eines Tages`) },
                },
                scales: {
                    x: { ...achsen(), beginAtZero: true, max: Math.ceil(Math.max(...auswahl.map((a) => a.mae)) * 1.5 * 10) / 10, title: { display: true, text: "mittlere Abweichung, kWh" } },
                    y: { ...achsen(), grid: { display: false }, ticks: { autoSkip: false, color: FARBE.text, font: { size: 12 } } },
                },
            },
            plugins: [wertBeschriftung],
        });
    });
}

// --- Was den Ertrag bestimmt --------------------------------------------------------------------

// für morgen stammt das Wetter aus der Vorhersage, nicht aus der ICON-D2-Analyse
const QUELLE_MORGEN = "Open-Meteo Wettervorhersage, ICON";
const NAME_MORGEN = { "Einstrahlung auf die Module": "Einstrahlung laut Vorhersage" };

function anteileJeWert(lage = "rueckblick") {
    const werte = (lage === "vorhersage" ? D.ergebnisse.importance_vorhersage : D.ergebnisse.importance).werte;
    const summe = werte.reduce((s, w) => s + Math.max(w.beitrag_mae, 0), 0);
    const je = Object.fromEntries(werte.map((w) => [w.merkmal, 100 * Math.max(w.beitrag_mae, 0) / summe]));
    return WERTE.map((w) => ({ ...w, anteil: w.merkmale.reduce((s, m) => s + (je[m] || 0), 0) }));
}

function einfluss() {
    const mitMorgen = Boolean(D.ergebnisse.importance_vorhersage);
    const zustand = { lage: "rueckblick" };
    const zeichnen = () => {
        const morgen = zustand.lage === "vorhersage";
        const liste = anteileJeWert(zustand.lage).filter((w) => w.anteil > 0).sort((a, b) => b.anteil - a.anteil)
            .map((w) => ({ ...w, name: morgen ? NAME_MORGEN[w.name] || w.name : w.name, herkunft: morgen && w.quelle === "wetter" ? QUELLE_MORGEN : QUELLEN[w.quelle] }));
        document.getElementById("chart-einfluss").parentElement.style.height = `${Math.max(260, liste.length * 30 + 60)}px`;
        chart("chart-einfluss", {
            type: "bar",
            data: { labels: liste.map((l) => l.name), datasets: [{ data: liste.map((l) => l.anteil), backgroundColor: liste.map((l, i) => i === 0 ? FARBE.dunkel : FARBE.gruen), borderRadius: 3, barPercentage: 0.75 }] },
            options: {
                indexAxis: "y",
                maintainAspectRatio: false,
                layout: { padding: { right: 16 } },
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: (c) => prozent(liste[c.dataIndex].anteil), afterLabel: (c) => `Quelle: ${liste[c.dataIndex].herkunft}` } },
                    wertBeschriftung: { texte: liste.map((l) => prozent(l.anteil)) },
                },
                scales: {
                    x: {
                        ...achsen(), type: "logarithmic", min: 0.01, max: 1000,
                        title: { display: true, text: "Anteil an der Vorhersage, logarithmisch" },
                        ticks: { font: { size: 11 }, autoSkip: false, maxRotation: 0, callback: (wert) => {
                            const stufe = Math.log10(wert);
                            return Math.abs(stufe - Math.round(stufe)) < 1e-9 && wert <= 100 ? `${String(Number(wert.toPrecision(1))).replace(".", ",")} %` : "";
                        } },
                    },
                    y: { ...achsen(), grid: { display: false }, ticks: { autoSkip: false, color: FARBE.text, font: { size: 12 } } },
                },
            },
            plugins: [wertBeschriftung],
        });
    };
    const knoepfe = mitMorgen ? `<div class="knopfleiste" id="einfluss-knoepfe">
            <button class="zeitraum-knopf aktiv" data-lage="rueckblick">im Nachhinein</button><button class="zeitraum-knopf" data-lage="vorhersage">für morgen</button>
        </div>` : "";
    return teil(`<section class="card">
        <div class="card-kopf"><h2>Was den Ertrag bestimmt</h2>${knoepfe}</div>
        <div class="chart-box"><canvas id="chart-einfluss"></canvas></div>
    </section>`, () => {
        if (mitMorgen) {
            document.getElementById("einfluss-knoepfe").addEventListener("click", (ereignis) => {
                const knopf = ereignis.target.closest(".zeitraum-knopf");
                if (!knopf) {
                    return;
                }
                zustand.lage = knopf.dataset.lage;
                document.querySelectorAll("#einfluss-knoepfe .zeitraum-knopf").forEach((b) => b.classList.toggle("aktiv", b === knopf));
                zeichnen();
            });
        }
        zeichnen();
    });
}

function datenquellen() {
    const werte = anteileJeWert();
    const marken = (quelle) => werte.filter((w) => w.quelle === quelle)
        .map((w) => `<span class="marke">${w.name} ${prozent(w.anteil)}</span>`).join(" ");
    const summe = (quelle) => werte.filter((w) => w.quelle === quelle).reduce((s, w) => s + w.anteil, 0);
    const zeilen = [
        ["Hoymiles, S-Miles Cloud", '<span class="marke marke-lernen">Tagesertrag</span> <span class="marke marke-lernen">aktuelle Leistung</span>', "wird vorhergesagt"],
        ["Open-Meteo Wettervorhersage, ICON", '<span class="marke marke-referenz">Einstrahlung</span> <span class="marke marke-referenz">Sonnenstunden</span> <span class="marke marke-referenz">Bewölkung</span> <span class="marke marke-referenz">Temperatur</span> <span class="marke marke-referenz">Regen</span>', "Wetterbericht der nächsten 7 Tage"],
        [QUELLEN.wetter, marken("wetter"), prozent(summe("wetter"))],
        [QUELLEN.satellit, marken("satellit"), prozent(summe("satellit"))],
        [QUELLEN.luft, marken("luft"), prozent(summe("luft"))],
        [QUELLEN.berechnet, marken("berechnet"), prozent(summe("berechnet"))],
    ].map((z) => `<tr><td><strong style="color:var(--color-heading)">${z[0]}</strong></td><td>${z[1]}</td><td class="num"><strong style="color:var(--color-heading)">${z[2]}</strong></td></tr>`).join("");
    const abgerufen = D.pipeline.letzter_lauf ? D.pipeline.letzter_lauf.gestartet : null;
    return teil(`<section class="card">
        <div class="card-kopf"><h2>Welche Daten abgerufen werden</h2><span class="legende">Daten zuletzt abgerufen ${zeitpunkt(abgerufen)} · Analyse zuletzt ${zeitpunkt(D.ergebnisse.trainiert_am)}</span></div>
        <div class="table-wrap"><table class="data-table">
            <thead><tr><th>Quelle</th><th>Abgerufene Werte</th><th class="num">Anteil im Nachhinein</th></tr></thead>
            <tbody>${zeilen}</tbody>
        </table></div>
    </section>`);
}

async function init() {
    const ziel = document.getElementById("analytics");
    try {
        const [prognose, verlauf, ergebnisse, pipeline, realtime] = await Promise.all([
            ladeJson("/api/analytics/prognose"),
            ladeJson("/api/analytics/verlauf?tage=500"),
            ladeJson("/api/analytics/ergebnisse"),
            ladeJson("/api/pipeline/status"),
            ladeJson("/api/hoymiles/realtime").catch(() => ({})),
        ]);
        D = { prognose, verlauf, ergebnisse, pipeline, realtime };
    } catch (fehler) {
        console.error(fehler);
        ziel.innerHTML = `<section class="card"><p class="empty">Noch keine Analyse vorhanden oder Daten nicht erreichbar. Unter <a href="/settings">Einstellungen</a> „Analyse jetzt neu rechnen“ starten.</p></section>`;
        return;
    }
    const inhalt = zusammen(kacheln(), wetterbericht(), messung(), verfahren(), einfluss(), datenquellen());
    ziel.innerHTML = inhalt.html;
    inhalt.nach.forEach((f) => f());
}

init();

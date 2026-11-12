/* Интерфейс CropMix Twin: ползунки площадей -> вода (у растения / на поле / из реки).
 * Данные: window.CROPMIX_MODEL из data/model.js (генерирует src/export_web.py). */
(function () {
  "use strict";
  var M = window.CROPMIX_MODEL;
  var Calc = window.CropMixCalc;
  var $ = function (id) { return document.getElementById(id); };
  if (!M || !Calc) {
    document.body.innerHTML = "<p class='warning'>Нет данных модели. Запустите <code>python -m src.run_all</code>.</p>";
    return;
  }

  var areas = {};
  var chart = null;
  var MEASURE_RU = { low: "низкий", base: "базовый", high: "высокий", pessimistic: "пессимистичный" };

  function fmt(x, digits) {
    return Number(x).toLocaleString("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }
  function mln(m3) { return fmt(m3 / 1e6, 0) + " млн м³"; }
  function km3(m3) { return fmt(m3 / 1e9, 2) + " км³"; }

  function fillSelect(el, items, selected) {
    el.innerHTML = "";
    items.forEach(function (it) {
      var o = document.createElement("option");
      o.value = it.value; o.textContent = it.label;
      if (it.value === selected) o.selected = true;
      el.appendChild(o);
    });
  }

  function scenarioOptions(list, unit, digits) {
    return list.map(function (m) {
      return { value: m.id, label: (MEASURE_RU[m.id] || m.id) + ": " + fmt(m.value, digits) + unit };
    });
  }

  function currentKey() {
    return Calc.scenarioKey($("eff-field").value, $("eff-canal").value, $("rice-perc").value);
  }

  function maxArea(cropId) {
    var m = 0;
    M.years.forEach(function (y) { m = Math.max(m, M.areas_ha[y][cropId]); });
    return Math.ceil(m * 1.5 / 1000) * 1000;
  }

  function buildSliders() {
    var box = $("sliders");
    box.innerHTML = "";
    M.crops.forEach(function (c) {
      var st = M.area_status[c.id];
      var row = document.createElement("div");
      row.className = "slider-row";
      row.innerHTML =
        "<div class='slider-head'><span class='crop-name'>" + c.name + "</span>" +
        "<span class='badge " + st.status + "' title='" + (st.note || ("источник: " + st.source)) + "'>" +
        (st.status === "derived" ? "вычислено из real" : st.status) + "</span></div>" +
        "<div class='proxy'>" + c.proxy + "</div>" +
        "<div class='slider-ctl'><input type='range' min='0' step='100' max='" + maxArea(c.id) +
        "' id='r-" + c.id + "' aria-label='Площадь: " + c.name + "'>" +
        "<input type='number' min='0' step='100' id='n-" + c.id + "' aria-label='Площадь, га: " + c.name + "'></div>";
      box.appendChild(row);
      var r = row.querySelector("#r-" + c.id), n = row.querySelector("#n-" + c.id);
      r.addEventListener("input", function () { areas[c.id] = Number(r.value); n.value = r.value; render(); });
      n.addEventListener("input", function () {
        var v = Math.max(0, Number(n.value) || 0);
        areas[c.id] = v; r.value = Math.min(v, Number(r.max)); render();
      });
    });
  }

  function setAreasFromYear(year) {
    M.crops.forEach(function (c) {
      areas[c.id] = M.areas_ha[year][c.id];  // точное значение из данных; округляется только при показе
      $("r-" + c.id).value = Math.round(areas[c.id]);
      $("n-" + c.id).value = Math.round(areas[c.id]);
    });
  }

  function renderWarning(riverM3) {
    var c = M.comparison;
    var items = M.warning_points.map(function (t) { return "<li>" + t + "</li>"; });
    items.splice(3, 0,
      "<li>Модельная оценка выше официальных показателей: <b>в " + fmt(c.ratio_base[0], 1) + "–" +
      fmt(c.ratio_base[1], 1) + " раза</b> при базовых КПД и <b>в " + fmt(c.ratio_all_scenarios[0], 1) + "–" +
      fmt(c.ratio_all_scenarios[1], 1) + " раза</b> по всем сценариям КПД и перколяции " +
      "(площади и климат того же года против лимита или плана на вегетацию; модель не калибровалась).</li>");
    var rows = c.rows.map(function (r) {
      return "<tr><td>" + r.year + "</td><td>" + r.official_label + " <span class='badge real'>real</span> " +
        r.official_source + "</td><td>" + km3(r.official_m3) + "</td><td>" + km3(r.model_river_m3) +
        "</td><td>×" + fmt(r.ratio, 2) + "</td></tr>";
    }).join("");
    var cur = c.rows.map(function (r) { return "×" + fmt(riverM3 / r.official_m3, 2) + " к " +
      r.official_label + " " + r.year; }).join("; ");
    $("warning").innerHTML =
      "<h3>⚠ Это не фактический водозабор</h3><ul>" + items.join("") + "</ul>" +
      "<p class='cur'>Текущий выбор: из реки " + km3(riverM3) + " — " + cur + ".</p>" +
      "<details><summary>Сравнение с официальными величинами (базовые КПД)</summary>" +
      "<table class='mini'><tr><th>Год</th><th>Официально</th><th>Величина</th><th>Модель</th><th>Отношение</th></tr>" +
      rows + "</table><p class='hint'>" + c.note + "</p></details>";
  }

  function renderTable(res) {
    var head = "<tr><th>Культура</th><th>Площадь, га</th><th>У растения, м³/га</th><th>На поле, м³/га</th>" +
      "<th>Из реки, м³/га</th><th>Из реки, млн м³</th></tr>";
    var body = res.rows.map(function (r) {
      return "<tr><td>" + r.name + "</td><td>" + fmt(r.area, 0) + "</td><td>" + fmt(r.coef.plant, 0) +
        "</td><td>" + fmt(r.coef.field, 0) + "</td><td>" + fmt(r.coef.river, 0) + "</td><td>" +
        fmt(r.river / 1e6, 1) + "</td></tr>";
    }).join("");
    var t = res.totals;
    var foot = "<tr class='sum'><td>Итого</td><td>" + fmt(t.area, 0) + "</td><td colspan='3'></td><td>" +
      fmt(t.river / 1e6, 1) + "</td></tr>";
    $("table").innerHTML = "<thead>" + head + "</thead><tbody>" + body + foot + "</tbody>";
  }

  function renderChart(res) {
    if (!window.Chart) { $("chart-fallback").hidden = false; return; }
    var labels = res.rows.map(function (r) { return r.name; });
    var data = [
      { label: "У растения", data: res.rows.map(function (r) { return r.plant / 1e6; }), backgroundColor: "#6aa84f" },
      { label: "На поле", data: res.rows.map(function (r) { return r.field / 1e6; }), backgroundColor: "#3d85c6" },
      { label: "Из реки", data: res.rows.map(function (r) { return r.river / 1e6; }), backgroundColor: "#1c4587" }
    ];
    if (chart) { chart.data.labels = labels; chart.data.datasets.forEach(function (d, i) { d.data = data[i].data; }); chart.update(); return; }
    chart = new window.Chart($("chart"), {
      type: "bar", data: { labels: labels, datasets: data },
      options: { responsive: true, maintainAspectRatio: false,
        scales: { y: { title: { display: true, text: "млн м³" } } },
        plugins: { tooltip: { callbacks: { label: function (ctx) { return ctx.dataset.label + ": " + fmt(ctx.parsed.y, 1) + " млн м³"; } } } } }
    });
  }

  function render() {
    var res = Calc.compute(M, currentKey(), $("climate-year").value, areas);
    var t = res.totals;
    $("t-plant").textContent = mln(t.plant);
    $("t-field").textContent = mln(t.field);
    $("t-river").textContent = mln(t.river);
    $("t-area").textContent = "Площадь в расчёте: " + fmt(t.area, 0) + " га (все посевы выбранных культур). " +
      "Сценарий: " + currentKey().replace(/\|/g, " / ") + "; климат: " +
      ($("climate-year").value === M.mean_key ? "среднее 2010–2025" : $("climate-year").value) + ".";
    renderWarning(t.river);
    renderTable(res);
    renderChart(res);
  }

  function init() {
    var total = M.data_status.filter(function (r) { return r.table === "ИТОГО"; })[0];
    $("data-banner").innerHTML = "Данные в <code>data/</code>: " + (total ? fmt(total.real, 0) + " чисел real, " +
      fmt(total.assumed, 0) + " assumed" : "") + ". Все КПД, Kc и параметры риса — <span class='badge assumed'>assumed</span>; " +
      "площади — <span class='badge real'>real</span> (stat.gov.kz); вода — <span class='badge model'>модель</span>.";

    var years = M.years.slice();
    fillSelect($("climate-year"), [{ value: M.mean_key, label: "среднее 2010–2025" }].concat(
      years.map(function (y) { return { value: y, label: y }; })), M.mean_key);
    fillSelect($("area-year"), years.slice().reverse().map(function (y) { return { value: y, label: y }; }),
      years[years.length - 1]);
    fillSelect($("eff-field"), scenarioOptions(M.scenarios.eff_field, "", 2), "base");
    fillSelect($("eff-canal"), scenarioOptions(M.scenarios.eff_canal, "", 3), "base");
    fillSelect($("rice-perc"), scenarioOptions(M.scenarios.rice_percolation, " мм/сут", 0), "base");

    buildSliders();
    setAreasFromYear($("area-year").value);
    ["climate-year", "eff-field", "eff-canal", "rice-perc"].forEach(function (id) { $(id).addEventListener("change", render); });
    $("area-year").addEventListener("change", function () { setAreasFromYear($("area-year").value); render(); });

    $("income").innerHTML = "<span class='badge na'>не рассчитывается</span> " + M.income.reason;
    $("limitations").innerHTML = M.limitations.map(function (t) { return "<li>" + t + "</li>"; }).join("");
    $("footer").textContent = "Данные модели от " + M.meta.generated + ". " + M.meta.units + ". Климат: " + M.meta.climate + ".";
    render();
  }

  init();
})();

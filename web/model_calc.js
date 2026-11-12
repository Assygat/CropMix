/* Расчёт для браузера: только Σ площадь × коэффициент (м³/га) из web/data/model.json.
 * Все коэффициенты посчитаны в Python (src/export_web.py); здесь нет формул модели.
 * Файл работает и в браузере (window.CropMixCalc), и в Node (тест tests/test_export_web.py). */
(function (root) {
  "use strict";

  function scenarioKey(field, canal, perc) {
    return field + "|" + canal + "|" + perc;
  }

  function cropRows(model, key, year, areas) {
    var byYear = model.coef_m3_ha[key];
    if (!byYear) throw new Error("Нет сценария " + key);
    var coef = byYear[year];
    if (!coef) throw new Error("Нет года " + year + " в сценарии " + key);
    return model.crops.map(function (crop) {
      var k = coef[crop.id];
      if (!k) throw new Error("Нет коэффициентов для " + crop.id);
      var a = Number(areas[crop.id]);
      if (!isFinite(a) || a < 0) a = 0;
      return {
        id: crop.id, name: crop.name, area: a,
        coef: { plant: k[0], field: k[1], river: k[2] },
        plant: a * k[0], field: a * k[1], river: a * k[2]
      };
    });
  }

  function totals(rows) {
    return rows.reduce(function (t, r) {
      t.area += r.area; t.plant += r.plant; t.field += r.field; t.river += r.river;
      return t;
    }, { area: 0, plant: 0, field: 0, river: 0 });
  }

  function compute(model, key, year, areas) {
    var rows = cropRows(model, key, year, areas);
    return { rows: rows, totals: totals(rows) };
  }

  var api = { scenarioKey: scenarioKey, cropRows: cropRows, totals: totals, compute: compute };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CropMixCalc = api;
})(this);

# CropMix Twin

**English summary.** CropMix Twin is a planning model of irrigation water use for Kyzylorda Region, Kazakhstan
(lower Syr Darya). It turns a crop mix and a climate year into river withdrawal: FAO-56 Penman–Monteith ET₀ × Kc,
effective rainfall, field and canal losses, rice flooding. It then uses linear programming to find crop mixes that fit
a water budget under explicit rules, and reports the binding constraints, shadow prices, climate stress tests and a
Monte Carlo uncertainty range. It is a planning model, not a field measurement, and it is **not validated** against
observed withdrawals. The six-page static website opens from `web/index.html`. Technical summary:
[docs/COMPETITION_TECHNICAL_SUMMARY.md](docs/COMPETITION_TECHNICAL_SUMMARY.md). Evidence behind each claim:
[docs/VERIFIED_CLAIMS.md](docs/VERIFIED_CLAIMS.md). The repository documentation below is in Russian; the website is in English.

**Licence.** Original code: MIT ([LICENSE](LICENSE)). Original documentation and other material by the author:
CC BY 4.0. Third-party data keep their own terms; the boundary data derived from OpenStreetMap/geoBoundaries
(`web/data/geo.*`) are ODbL 1.0. Details: [NOTICE.md](NOTICE.md).

---

Инструмент планирования структуры посевов для Кызылординской области (Казахстан):
как замена одних культур другими меняет водопотребление и какая структура
экономит воду при заданных ограничениях. Основа расчёта — ETc = ET0 × Kc (FAO-56).
Доход в основной модели не считается: нет затрат и части урожайностей и цен (цель «стоимость» в Decision Lab
доступна только по коэффициентам, которые введёт пользователь).

Это модель для планирования, а не измерение на поле.

- План работы: [docs/plan.md](docs/plan.md)
- Правила проекта: [CLAUDE.md](CLAUDE.md)
- Источники данных: [data/SOURCES.md](data/SOURCES.md)
- Ограничения модели и данных: [docs/limitations.md](docs/limitations.md)
- Decision Lab (2026-11-17: режим дефицита, стресс-тесты, Монте-Карло, проверка входов): [docs/decision_lab.md](docs/decision_lab.md)
- Пакет для конкурса (англ.: результаты, инновация, демо-сценарий, план презентации): [docs/competition_package.md](docs/competition_package.md)
- Текст заявки на конкурс (англ.): [docs/COMPETITION_SUBMISSION.md](docs/COMPETITION_SUBMISSION.md)
- Финальный аудит (2026-11-17): [docs/FINAL_AUDIT_REPORT.md](docs/FINAL_AUDIT_REPORT.md), [docs/VERIFIED_CLAIMS.md](docs/VERIFIED_CLAIMS.md), [docs/COMPETITION_TECHNICAL_SUMMARY.md](docs/COMPETITION_TECHNICAL_SUMMARY.md)

## Установка, пересчёт и тесты (Windows) — по порядку

Папка `outputs/` (30 CSV: 15 — модули 1–9, 15 — Decision Lab) **намеренно не хранится в Git** (`.gitignore`): её создаёт
шаг 3. В свежем клоне её нет, поэтому тесты, сверяющие результаты, запускайте только после шага 3
(без `outputs/` три таких теста в `tests/test_sim_core.py` пропускаются с подсказкой выполнить `run_all`).

1. Создать и активировать виртуальное окружение:

   ```
   py -3.14 -m venv .venv
   .venv\Scripts\activate
   ```

   (в PowerShell: `.venv\Scripts\Activate.ps1`). Команды ниже указывают `.venv\Scripts\python` явно и работают
   и без активации.

2. Установить зависимости из закреплённого набора:

   ```
   .venv\Scripts\python -m pip install -r requirements-lock.txt
   ```

3. Пересчитать модель (≈ 1.5–2 мин) — создаёт `outputs/` и обновляет `web/data/model.json`, `web/data/model.js`,
   `web/data/planner.json`, `web/data/planner.js`:

   ```
   .venv\Scripts\python -m src.run_all
   ```

4. Тесты Python (241 тест; `tests/test_sim_core.py` запускает и все JS-тесты, а `tests/test_planner_crosscheck.py`
   сверяет браузерный решатель с SciPy, если установлен Node.js; без Node эти тесты пропускаются):

   ```
   .venv\Scripts\python -m pytest
   ```

5. Тесты Node отдельно (79 тестов; кавычки обязательны: шаблон раскрывает сам Node; форма с папкой `tests/js/` в Node 24
   не работает):

   ```
   node --test "tests/js/*.test.js"
   ```

Проверено только на Windows 11 с CPython 3.14.2 (64-bit) и версиями из `requirements-lock.txt` (полный закреплённый
набор, на нём получены `outputs/` и проходят все тесты). `requirements.txt` — прямые зависимости в тех же версиях.
Другие версии Python и пакетов не проверялись. Для тестов симулятора нужен Node.js (проверено на v24.22.1).

## Сайт

Открыть `web/index.html` двойным щелчком (сервер не нужен). Шесть страниц на английском: Home, Simulator,
Decision Lab, Methodology, Data & Evidence, About — общая навигация, без фреймворков. Устройство сайта, общие файлы и где
теперь функции старого калькулятора: `docs/website.md`. Числа на страницах сверяет с outputs/ `tests/test_site.py`.

## Decision Lab (`web/planner.html`, 2026-11-17)

Планировщик для маловодного года: доля воды, правила (минимум площади культуры, максимум роста, минимум
продовольственных, можно ли не сеять часть земли), цель (площадь / продовольственные / вода / стоимость по
введённым коэффициентам). LP решается в браузере (`lp_solver.js`, `planner_core.js`) и сверяется с SciPy/HiGHS
(`tests/test_planner_crosscheck.py`). Python-модули: `src/portfolio.py`, `src/climate_stress.py`,
`src/uncertainty.py`, `src/validation.py`, сборка — `src/decision_support.py` (вызывается из `run_all`).
Подробно: `docs/decision_lab.md`.

## Симулятор структуры посевов

Открыть `web/simulator.html` двойным щелчком (сервер и интернет не нужны). Карта области, редактор площадей,
выбор климата и КПД, сравнение исходной, пользовательской и оптимизированной структур. Это модель для
планирования, а не измерение; модель не валидирована. Подробно: `docs/simulator.md`.

Режим карты **Edit map** (Crop Editor) показывает **схематичную** мозаику посевов: 1 шестиугольная ячейка = 100 га
посевной площади. Расположение ячеек условное — геопривязанных данных о полях в проекте нет, и мозаика
**не показывает, где на самом деле растёт культура**. Кистью можно перекрасить ячейки: каждая ячейка переносит
100 га с одной культуры на другую, ластик убирает посевную площадь. Мозаика и таблица площадей — одно и то же
состояние сценария: вода считается той же моделью, что и для таблицы. Ограничения мозаики —
`docs/limitations.md`, раздел «Симулятор».

После пересчёта модели обновить данные симулятора (`web/data/simulator.js`, `web/data/geo.js`):

```
.venv\Scripts\python -m src.run_all
.venv\Scripts\python -m src.export_simulator
```

## Отчёт по данным (сколько чисел real / assumed / simulated)

```
.venv\Scripts\python -m src.data_report
```

## Лицензии и сторонние данные

- Исходный код — MIT ([LICENSE](LICENSE)). Документация, тексты сайта и другие собственные материалы автора —
  CC BY 4.0. Сторонние данные — на условиях их источников: NASA POWER, NOAA GSOD, geoBoundaries / OpenStreetMap
  (ODbL 1.0, включая производные `web/data/geo.*`), Natural Earth (public domain). Границы — в [NOTICE.md](NOTICE.md).
- 14 сторонних документов (FAO, CAWater-Info, САНИИРИ, SIAR) в текущую версию репозитория не входят: права на их
  распространение не ясны. Ссылки, цитаты и контрольные суммы — [data/SOURCES.md](data/SOURCES.md),
  [data/raw/README.md](data/raw/README.md), `data/raw/SHA256SUMS`. Код и тесты эти файлы не читают.

## Структура

```
data/    исходные данные (CSV) и SOURCES.md
src/     расчётный код
tests/   тесты
web/     интерфейс
docs/    план, методология, ограничения
```

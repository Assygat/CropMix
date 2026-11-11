# CropMix Twin

Инструмент планирования структуры посевов для Кызылординской области (Казахстан):
как замена одних культур другими меняет водопотребление и доход, и какая структура
экономит воду при заданных ограничениях. Основа расчёта — ETc = ET0 × Kc (FAO-56).

Это модель для планирования, а не измерение на поле.

- План работы: [docs/plan.md](docs/plan.md)
- Правила проекта: [CLAUDE.md](CLAUDE.md)
- Источники данных: [data/SOURCES.md](data/SOURCES.md)
- Ограничения модели и данных: [docs/limitations.md](docs/limitations.md)

## Установка (Windows)

```
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

## Тесты

```
.venv\Scripts\python -m pytest
```

## Отчёт по данным (сколько чисел real / assumed / simulated)

```
.venv\Scripts\python -m src.data_report
```

## Структура

```
data/    исходные данные (CSV) и SOURCES.md
src/     расчётный код
tests/   тесты
web/     интерфейс
docs/    план, методология, ограничения
```

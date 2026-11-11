import pandas as pd

from src.data_report import assumed_rows, main, summarize


def table(statuses):
    return pd.DataFrame(
        {
            "entity": [f"crop{i}" for i in range(len(statuses))],
            "param": "kc_mid",
            "year": None,
            "value": 1.0,
            "unit": "-",
            "source": "x",
            "status": statuses,
        }
    )


def test_summarize_counts_by_status():
    tables = {"crops": table(["real", "assumed", "assumed"]), "areas": table(["simulated"])}
    s = summarize(tables).set_index("table")
    assert s.loc["crops", ["real", "assumed", "simulated", "total"]].tolist() == [1, 2, 0, 3]
    assert s.loc["areas", ["real", "assumed", "simulated", "total"]].tolist() == [0, 0, 1, 1]


def test_summarize_total_row_and_real_share():
    tables = {"crops": table(["real", "assumed", "assumed"]), "areas": table(["real"])}
    total = summarize(tables).set_index("table").loc["ИТОГО"]
    assert total["total"] == 4
    assert total["real"] == 2
    assert total["real_pct"] == 50.0


def test_assumed_rows_lists_only_assumed():
    tables = {"crops": table(["real", "assumed", "simulated", "assumed"])}
    a = assumed_rows(tables)
    assert len(a) == 2
    assert set(a["entity"]) == {"crop1", "crop3"}
    assert (a["table"] == "crops").all()


def test_main_on_empty_data_dir(tmp_path, capsys):
    assert main(tmp_path) == 0
    assert "пока нет CSV" in capsys.readouterr().out


def test_main_reports_validation_errors(tmp_path, capsys):
    table(["guess"]).to_csv(tmp_path / "bad.csv", index=False, encoding="utf-8")
    assert main(tmp_path) == 1
    assert "status 'guess'" in capsys.readouterr().out

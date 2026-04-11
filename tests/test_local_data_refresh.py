import unittest
from pathlib import Path
import shutil
import uuid

import pandas as pd

from local_data_refresh import build_emxc_spliced, write_price_panel


class BuildEmxcSplicedTests(unittest.TestCase):
    def test_scales_emxc_series_after_switch_date(self):
        index = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"])
        frame = pd.DataFrame(
            {
                "EEM": [100.0, 105.0, 110.0],
                "EMXC": [pd.NA, 50.0, 55.0],
            },
            index=index,
        )

        out = build_emxc_spliced(frame, pd.Timestamp("2020-01-02"))

        self.assertAlmostEqual(out.loc[pd.Timestamp("2020-01-01")], 100.0)
        self.assertAlmostEqual(out.loc[pd.Timestamp("2020-01-02")], 105.0)
        self.assertAlmostEqual(out.loc[pd.Timestamp("2020-01-03")], 115.5)


class WritePricePanelTests(unittest.TestCase):
    def test_writes_sorted_csv_and_returns_latest_date(self):
        frame = pd.DataFrame(
            {"QQQ": [503.0, 500.0]},
            index=pd.to_datetime(["2026-04-02", "2026-04-01"]),
        )
        frame.index.name = "date"

        tmpdir = Path.cwd() / f"test_tmp_{uuid.uuid4().hex}"
        tmpdir.mkdir()
        try:
            path = tmpdir / "panel.csv"
            latest = write_price_panel(path, frame)
            written = pd.read_csv(path)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        self.assertEqual(latest, pd.Timestamp("2026-04-02"))
        self.assertEqual(written["date"].tolist(), ["2026-04-01", "2026-04-02"])
        self.assertEqual(written["QQQ"].tolist(), [500.0, 503.0])


if __name__ == "__main__":
    unittest.main()

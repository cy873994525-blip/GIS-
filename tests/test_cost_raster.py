# -*- coding: utf-8 -*-
"""甲（数据与坐标层）第一次进度：栅格加载与基础校验测试。

运行：
    python -m unittest discover -s tests -p "test_cost_raster.py" -v
"""

import json
import tempfile
import unittest
from pathlib import Path

from cost_raster import (
    RasterError,
    build_raster,
    load_raster_file,
    in_bounds,
    is_nodata,
    get_cost,
    raster_summary,
)

SAMPLE_4X4 = Path(__file__).resolve().parent.parent / "sample_data" / "cost_grid_4x4.json"


class TestBuildRaster(unittest.TestCase):
    def test_basic_matrix_shape_and_values(self):
        raster = build_raster([[5, 7, 8, 4], [4, 5, 7, 8]])
        self.assertEqual(raster["rows"], 2)
        self.assertEqual(raster["cols"], 4)
        self.assertEqual(raster["values"][0], [5.0, 7.0, 8.0, 4.0])
        self.assertEqual(raster["bounds"], [0.0, 0.0, 4.0, 2.0])

    def test_nodata_marked_and_cost_kept(self):
        raster = build_raster([[5, -9999], [4, 7]], nodata=-9999)
        self.assertTrue(is_nodata(raster, 0, 1))
        self.assertFalse(is_nodata(raster, 1, 0))
        self.assertEqual(get_cost(raster, 1, 0), 4.0)
        with self.assertRaises(RasterError):
            get_cost(raster, 0, 1)

    def test_in_bounds_check(self):
        raster = build_raster([[5, 7], [8, 4]])
        self.assertTrue(in_bounds(raster, 0, 0))
        self.assertTrue(in_bounds(raster, 1, 1))
        self.assertFalse(in_bounds(raster, -1, 0))
        self.assertFalse(in_bounds(raster, 2, 1))
        self.assertFalse(in_bounds(raster, 0, 3))

    def test_get_cost_out_of_bounds_raises(self):
        raster = build_raster([[5, 7], [8, 4]])
        with self.assertRaises(RasterError):
            get_cost(raster, 0, 5)

    def test_ragged_rows_rejected(self):
        with self.assertRaises(RasterError):
            build_raster([[5, 7, 8], [4, 5]])

    def test_non_numeric_cost_rejected(self):
        with self.assertRaises(RasterError):
            build_raster([[5, "x"], [8, 4]])

    def test_negative_cost_rejected(self):
        with self.assertRaises(RasterError):
            build_raster([[5, -3], [8, 4]])

    def test_summary_counts_and_range(self):
        raster = build_raster([[5, -9999], [4, 7]], nodata=-9999)
        summary = raster_summary(raster)
        self.assertEqual(summary["cell_count"], 4)
        self.assertEqual(summary["nodata_count"], 1)
        self.assertEqual(summary["cost_min"], 4.0)
        self.assertEqual(summary["cost_max"], 7.0)


class TestLoadRasterFile(unittest.TestCase):
    def test_load_bundled_4x4_sample(self):
        raster = load_raster_file(SAMPLE_4X4)
        self.assertEqual(raster["rows"], 4)
        self.assertEqual(raster["cols"], 4)
        self.assertEqual(raster["nodata"], -9999.0)
        self.assertTrue(is_nodata(raster, 1, 1))
        summary = raster_summary(raster)
        self.assertEqual(summary["nodata_count"], 1)
        self.assertEqual(summary["cost_min"], 4.0)
        self.assertEqual(summary["cost_max"], 8.0)

    def test_load_valid_json_roundtrip(self):
        payload = {
            "crs": "unknown",
            "nodata": -9999,
            "origin": [0, 3],
            "pixel_size": [1, 1],
            "values": [[5, 7, 8], [4, 5, 7], [8, 4, 5]],
        }
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "grid.json"
            f.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            raster = load_raster_file(f)
            self.assertEqual((raster["rows"], raster["cols"]), (3, 3))
            self.assertEqual(get_cost(raster, 2, 2), 5.0)

    def test_missing_file_raises(self):
        with self.assertRaises(RasterError):
            load_raster_file(Path(tempfile.gettempdir()) / "no_such_raster.json")

    def test_bad_json_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "bad.json"
            f.write_text("{not json", encoding="utf-8")
            with self.assertRaises(RasterError):
                load_raster_file(f)

    def test_malformed_matrix_raises(self):
        payload = {"values": [[5, 7], [4]]}
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "malformed.json"
            f.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(RasterError):
                load_raster_file(f)


if __name__ == "__main__":
    unittest.main()

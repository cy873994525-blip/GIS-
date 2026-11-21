# -*- coding: utf-8 -*-
"""甲第二次进度：坐标 ↔ 行列号双向换算测试。

运行：
    python -m unittest discover -s tests -p "test_coord_transform.py" -v
"""

import math
import unittest
from pathlib import Path

from cost_raster import build_raster, load_raster_file
from coord_transform import (
    CoordError,
    EPS,
    cell_to_map,
    describe_cell,
    format_coord,
    from_geotransform,
    map_to_cell,
    parse_coord_text,
    raster_extent,
    require_passable,
    resolve_point,
    to_geotransform,
)

SAMPLE_4X4 = Path(__file__).resolve().parent.parent / "sample_data" / "cost_grid_4x4.json"


def plain_4x4():
    return build_raster([[5, 7, 8, 4], [4, 5, 7, 8], [7, 8, 4, 5], [8, 4, 5, 7]])


class TestCellToMap(unittest.TestCase):
    def test_center_of_first_cell(self):
        raster = plain_4x4()
        x, y = cell_to_map(raster, 0, 0)
        self.assertAlmostEqual(x, 0.5)
        self.assertAlmostEqual(y, 3.5)

    def test_center_of_last_cell(self):
        raster = plain_4x4()
        x, y = cell_to_map(raster, 3, 3)
        self.assertAlmostEqual(x, 3.5)
        self.assertAlmostEqual(y, 0.5)

    def test_corner_anchor_is_upper_left(self):
        raster = plain_4x4()
        x, y = cell_to_map(raster, 1, 2, anchor="corner")
        self.assertAlmostEqual(x, 2.0)
        self.assertAlmostEqual(y, 3.0)

    def test_non_square_pixel_size(self):
        raster = build_raster([[5, 7], [8, 4]], origin=[100.0, 400.0], pixel_size=[30.0, 60.0])
        x, y = cell_to_map(raster, 0, 0)
        self.assertAlmostEqual(x, 115.0)
        self.assertAlmostEqual(y, 370.0)

    def test_out_of_range_cell_rejected(self):
        raster = plain_4x4()
        with self.assertRaises(CoordError):
            cell_to_map(raster, 0, 4)
        with self.assertRaises(CoordError):
            cell_to_map(raster, -1, 0)

    def test_non_integer_cell_rejected(self):
        with self.assertRaises(CoordError):
            cell_to_map(plain_4x4(), 0.5, 1)


class TestMapToCell(unittest.TestCase):
    def test_roundtrip_all_cells(self):
        raster = plain_4x4()
        for row in range(raster["rows"]):
            for col in range(raster["cols"]):
                x, y = cell_to_map(raster, row, col)
                self.assertEqual(map_to_cell(raster, x, y), (row, col))

    def test_roundtrip_precision(self):
        raster = build_raster([[5, 7], [8, 4]], origin=[-180.0, 90.0], pixel_size=[0.1, 0.1])
        for row in range(raster["rows"]):
            for col in range(raster["cols"]):
                x, y = cell_to_map(raster, row, col)
                got = map_to_cell(raster, x, y)
                self.assertEqual(got, (row, col), "往返换算错位：{}".format(got))

    def test_exact_right_and_bottom_edge_go_to_last_cell(self):
        raster = plain_4x4()
        xmin, ymin, xmax, ymax = raster_extent(raster)
        # 恰好落在右边界 / 下边界，按 GDAL 闭区间归入最后一列 / 最后一行
        self.assertEqual(map_to_cell(raster, xmax, 1.5), (2, 3))
        self.assertEqual(map_to_cell(raster, 0.5, ymin), (3, 0))

    def test_outside_extent_rejected(self):
        raster = plain_4x4()
        xmin, ymin, xmax, ymax = raster_extent(raster)
        with self.assertRaises(CoordError):
            map_to_cell(raster, xmax + 1.0, 1.0)
        with self.assertRaises(CoordError):
            map_to_cell(raster, 1.0, ymin - 1.0)

    def test_tiny_float_noise_within_tolerance(self):
        raster = plain_4x4()
        xmin, ymin, xmax, ymax = raster_extent(raster)
        # 越界量小于 EPS 时不应报错
        self.assertEqual(map_to_cell(raster, xmin - EPS * 0.5, 1.5), (2, 0))

    def test_non_numeric_coordinate_rejected(self):
        raster = plain_4x4()
        with self.assertRaises(CoordError):
            map_to_cell(raster, "100", 1.0)
        with self.assertRaises(CoordError):
            map_to_cell(raster, math.nan, 1.0)

    def test_nodata_cell_still_maps(self):
        """换算层只负责定位，是否可通行由 require_passable / 引擎判断。"""
        raster = load_raster_file(SAMPLE_4X4)
        point = describe_cell(raster, 1, 1, role="起点")
        self.assertTrue(point["blocked"])
        self.assertIsNone(point["cost"])
        with self.assertRaises(CoordError):
            require_passable(point)


class TestParseCoordText(unittest.TestCase):
    def test_comma_and_space_and_semicolon(self):
        for text in ("100,200", "100 200", "100, 200", "100;200", "100\t200"):
            self.assertEqual(parse_coord_text(text), (100.0, 200.0), text)

    def test_brackets_and_fullwidth(self):
        self.assertEqual(parse_coord_text("（１００，２００）"), (100.0, 200.0))
        self.assertEqual(parse_coord_text("(100,200)"), (100.0, 200.0))

    def test_negative_and_decimal(self):
        self.assertEqual(parse_coord_text("-116.5, 40.2"), (-116.5, 40.2))

    def test_scientific_notation(self):
        self.assertEqual(parse_coord_text("1e3, 2E3"), (1000.0, 2000.0))

    def test_wrong_token_count_rejected(self):
        for text in ("100", "100 200 300", ","):
            with self.assertRaises(CoordError, msg=text):
                parse_coord_text(text)

    def test_empty_rejected(self):
        for text in ("", "   ", None, "()"):
            with self.assertRaises(CoordError, msg=repr(text)):
                parse_coord_text(text)

    def test_illegal_char_rejected(self):
        with self.assertRaises(CoordError):
            parse_coord_text("100a,200")

    def test_format_coord_roundtrip(self):
        text = format_coord(116.1234, 39.9876, precision=3)
        self.assertEqual(text, "116.123, 39.988")
        self.assertEqual(parse_coord_text(text), (116.123, 39.988))


class TestResolvePoint(unittest.TestCase):
    def test_keyboard_input_to_cell(self):
        raster = plain_4x4()
        point = resolve_point(raster, "0.5, 3.5", role="起点")
        self.assertEqual((point["row"], point["col"]), (0, 0))
        self.assertEqual(point["cost"], 5.0)
        self.assertFalse(point["blocked"])
        self.assertIn("第 1 行第 1 列", point["message"])

    def test_outside_input_rejected_with_message(self):
        raster = plain_4x4()
        with self.assertRaises(CoordError) as ctx:
            resolve_point(raster, "10, 10")
        self.assertIn("超出图幅", str(ctx.exception))

    def test_passable_point_passes_require(self):
        raster = plain_4x4()
        point = resolve_point(raster, "3.5, 0.5")
        self.assertEqual((point["row"], point["col"]), (3, 3))
        self.assertIs(require_passable(point), point)

    def test_geographic_coordinates(self):
        """经纬度像元：负经度、北纬，验证 y 方向不搞反。"""
        raster = build_raster([[5, 7, 8], [4, 5, 7]],
                              origin=[-116.50, 40.30], pixel_size=[0.01, 0.01],
                              crs="EPSG:4326")
        point = resolve_point(raster, "-116.495, 40.295")
        self.assertEqual((point["row"], point["col"]), (0, 0))
        # 更北的坐标应落在更靠上的行
        north = resolve_point(raster, "-116.495, 40.295")
        south = resolve_point(raster, "-116.495, 40.285")
        self.assertEqual((north["row"], south["row"]), (0, 1))


class TestGeoTransform(unittest.TestCase):
    def test_from_geotransform_basic(self):
        gt = (100.0, 30.0, 0.0, 400.0, 0.0, -60.0)
        raster = from_geotransform(gt, 2, 2, [[5, 7], [8, 4]])
        self.assertEqual(raster["origin"], [100.0, 400.0])
        self.assertEqual(raster["pixel_size"], [30.0, 60.0])
        self.assertEqual(raster_extent(raster), (100.0, 280.0, 160.0, 400.0))

    def test_rotation_rejected(self):
        gt = (100.0, 30.0, 0.5, 400.0, 0.0, -60.0)
        with self.assertRaises(CoordError) as ctx:
            from_geotransform(gt, 2, 2, [[5, 7], [8, 4]])
        self.assertIn("旋转", str(ctx.exception))

    def test_positive_sy_rejected(self):
        gt = (100.0, 30.0, 0.0, 400.0, 0.0, 60.0)
        with self.assertRaises(CoordError):
            from_geotransform(gt, 2, 2, [[5, 7], [8, 4]])

    def test_matrix_size_mismatch_rejected(self):
        gt = (0.0, 1.0, 0.0, 4.0, 0.0, -1.0)
        with self.assertRaises(CoordError):
            from_geotransform(gt, 4, 4, [[5, 7], [8, 4]])

    def test_to_geotransform_roundtrip(self):
        raster = plain_4x4()
        gt = to_geotransform(raster)
        back = from_geotransform(gt, raster["rows"], raster["cols"], raster["values"])
        self.assertEqual(back["origin"], raster["origin"])
        self.assertEqual(back["pixel_size"], raster["pixel_size"])
        for row in range(4):
            for col in range(4):
                self.assertEqual(cell_to_map(back, row, col), cell_to_map(raster, row, col))


if __name__ == "__main__":
    unittest.main()

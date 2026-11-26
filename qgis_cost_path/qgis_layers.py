import math

from qgis.PyQt.QtCore import QMetaType
from qgis.core import (
    Qgis,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsPointXY,
    QgsRasterLayer,
    QgsRendererCategory,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)

from .core.coord_transform import cell_to_map, from_geotransform
from .core.cost_rules import path_length_m


def raster_crs(raster):
    crs = QgsCoordinateReferenceSystem()
    name = raster.get("crs", "unknown")
    if name and str(name).lower() != "unknown":
        crs.createFromUserInput(str(name))
    return crs


def read_qgis_raster(layer, max_cells=None):
    from osgeo import gdal

    if not isinstance(layer, QgsRasterLayer):
        raise ValueError("请先在 QGIS 图层列表中选中成本栅格。")
    if layer.providerType() != "gdal":
        raise ValueError("当前只支持由 GDAL 读取的本地 GeoTIFF。")

    dataset = gdal.Open(layer.source(), gdal.GA_ReadOnly)
    if dataset is None:
        raise ValueError("无法读取当前栅格文件。")
    if dataset.GetDriver().ShortName != "GTiff":
        raise ValueError("当前只支持 GeoTIFF 成本栅格。")

    rows = dataset.RasterYSize
    cols = dataset.RasterXSize
    if max_cells is not None and rows * cols > max_cells:
        raise ValueError(
            "当前窗口最多显示 {:,} 格，所选栅格为 {} × {}。".format(
                max_cells, rows, cols
            )
        )

    transform = dataset.GetGeoTransform(can_return_null=True)
    if transform is None:
        raise ValueError("所选 GeoTIFF 没有地理变换信息。")
    if not dataset.GetProjection() or not layer.crs().isValid():
        raise ValueError("所选 GeoTIFF 没有有效坐标系。")

    band = dataset.GetRasterBand(1)
    if band is None:
        raise ValueError("无法读取 GeoTIFF 的第 1 波段。")
    raw = band.ReadAsArray()
    mask = band.GetMaskBand().ReadAsArray()
    if raw is None or mask is None:
        raise ValueError("无法读取第 1 波段或 NoData 掩膜。")

    nodata = -9999.0
    values = []
    for data_row, mask_row in zip(raw.tolist(), mask.tolist()):
        output_row = []
        for value, valid in zip(data_row, mask_row):
            if valid and math.isfinite(value):
                if float(value) == nodata:
                    raise ValueError(
                        "栅格中存在有效成本值 -9999，和插件的 NoData 标记冲突。"
                    )
                output_row.append(float(value))
            else:
                output_row.append(nodata)
        values.append(output_row)

    crs = layer.crs()
    return from_geotransform(
        transform,
        rows,
        cols,
        values,
        nodata=nodata,
        crs=crs.authid() or crs.toWkt(),
    )


def create_layer(geometry_type, name, crs, fields):
    layer = QgsVectorLayer(geometry_type, name, "memory")
    if not layer.isValid():
        raise ValueError("无法创建图层：{}".format(name))
    layer.setCrs(crs)
    qgis_fields = [
        QgsField(field_name, field_type)
        for field_name, field_type in fields
    ]
    if not layer.dataProvider().addAttributes(qgis_fields):
        raise ValueError("无法创建图层字段：{}".format(name))
    layer.updateFields()
    return layer


def create_feature(layer, geometry, attributes):
    feature = QgsFeature(layer.fields())
    feature.setGeometry(geometry)
    feature.setAttributes(attributes)
    return feature


def add_features(layer, features):
    success, _ = layer.dataProvider().addFeatures(features)
    if not success:
        raise ValueError("无法向图层写入要素：{}".format(layer.name()))
    layer.updateExtents()


def make_result_layers(raster, result):
    crs = raster_crs(raster)
    if not crs.isValid():
        raise ValueError("当前成本栅格没有有效 CRS，不能添加到 QGIS 地图。")

    path = result.path
    stats = result.stats
    points = [
        QgsPointXY(*cell_to_map(raster, row, col))
        for row, col in path
    ]

    integer_type = QMetaType.Int
    real_type = QMetaType.Double
    string_type = QMetaType.QString
    layers = []

    if len(points) > 1:
        route_layer = create_layer(
            "LineString",
            "最小成本路径",
            crs,
            (
                ("seq", integer_type),
                ("from_row", integer_type),
                ("from_col", integer_type),
                ("to_row", integer_type),
                ("to_col", integer_type),
                ("step_cost", real_type),
                ("cum_cost", real_type),
                ("total_cost", real_type),
                ("length", real_type),
                ("length_m", real_type),
                ("steps", integer_type),
                ("algorithm", string_type),
            ),
        )

        length_m = None
        if not crs.isGeographic() and crs.mapUnits() == Qgis.DistanceUnit.Meters:
            length_m = path_length_m(path, tuple(raster["pixel_size"]))

        route_features = []
        for index, step in enumerate(stats["step_details"]):
            geometry = QgsGeometry.fromPolylineXY(points[index:index + 2])
            attributes = [
                index + 1,
                step["from"][0],
                step["from"][1],
                step["to"][0],
                step["to"][1],
                step["step_cost"],
                step["cumulative"],
                stats["total_cost"],
                stats["length"],
                length_m,
                stats["steps"],
                stats["algorithm"],
            ]
            route_features.append(
                create_feature(route_layer, geometry, attributes)
            )

        add_features(route_layer, route_features)
        route_layer.renderer().setSymbol(
            QgsLineSymbol.createSimple({
                "line_color": "#087f8c",
                "line_width": "0.85",
            })
        )
        layers.append(route_layer)

    endpoint_layer = create_layer(
        "Point",
        "成本路径端点",
        crs,
        (
            ("role", string_type),
            ("row", integer_type),
            ("col", integer_type),
        ),
    )

    endpoint_definitions = (
        [("起点", 0), ("终点", -1)]
        if len(points) > 1
        else [("起点 / 终点", 0)]
    )
    endpoint_features = [
        create_feature(
            endpoint_layer,
            QgsGeometry.fromPointXY(points[index]),
            [role, path[index][0], path[index][1]],
        )
        for role, index in endpoint_definitions
    ]
    add_features(endpoint_layer, endpoint_features)

    categories = []
    for role, color in (
        ("起点", "#006c60"),
        ("终点", "#994523"),
        ("起点 / 终点", "#4355a3"),
    ):
        symbol = QgsMarkerSymbol.createSimple({
            "name": "circle",
            "color": color,
            "outline_color": "#ffffff",
            "size": "4",
        })
        categories.append(QgsRendererCategory(role, symbol, role))

    endpoint_layer.setRenderer(
        QgsCategorizedSymbolRenderer("role", categories)
    )
    labels = QgsPalLayerSettings()
    labels.fieldName = "role"
    endpoint_layer.setLabeling(QgsVectorLayerSimpleLabeling(labels))
    endpoint_layer.setLabelsEnabled(True)
    layers.append(endpoint_layer)
    return layers

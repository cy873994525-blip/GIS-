import heapq
import math

from .core.contract import PathResult, shortest_path
from .core.cost_path import NoRouteError
from .core.cost_rules import (
    can_step,
    distance_factor,
    neighbor_steps,
    neighbors,
    path_step_details,
    path_total_cost,
    raster_shape,
    resolve_config,
    step_cost,
)


def raster_with_obstacles(raster, blocked_cells):
    if not blocked_cells:
        return raster
    nodata = raster.get("nodata")
    if nodata is None:
        nodata = -9999.0
    values = [list(row) for row in raster["values"]]
    for row, col in blocked_cells:
        if 0 <= row < raster["rows"] and 0 <= col < raster["cols"]:
            values[row][col] = nodata
    result = dict(raster)
    result["values"] = values
    result["nodata"] = nodata
    return result


def combine_results(cost, results, config, algorithm):
    path = []
    expanded = 0
    elapsed = 0.0
    for result in results:
        segment = list(result.path)
        if path:
            segment = segment[1:]
        path.extend(segment)
        expanded += result.stats["expanded"]
        elapsed += result.stats["elapsed_ms"]

    details = path_step_details(cost, path, config)
    total_cost = path_total_cost(cost, path, config)
    length = sum(
        distance_factor(first, second, config)
        for first, second in zip(path, path[1:])
    )
    return PathResult(
        path=path,
        stats={
            "total_cost": total_cost,
            "length": length,
            "steps": max(0, len(path) - 1),
            "expanded": expanded,
            "elapsed_ms": elapsed,
            "step_details": details,
            "algorithm": algorithm,
        },
    )


def route_through(cost, start, waypoints, goal, config, algorithm):
    stops = [start] + list(waypoints) + [goal]
    results = []
    for first, second in zip(stops, stops[1:]):
        results.append(
            shortest_path(
                cost,
                first,
                second,
                config=config,
                algorithm=algorithm,
            )
        )
    return combine_results(cost, results, config, algorithm), results


def _reverse_shortest_tree(cost, goal, config):
    shape = raster_shape(cost)
    distances = {goal: 0.0}
    next_cell = {}
    queue = [(0.0, goal)]

    while queue:
        current_distance, current = heapq.heappop(queue)
        if current_distance != distances.get(current):
            continue

        for previous, _factor, _diagonal in neighbors(current, shape, config):
            if not can_step(cost, previous, current, config):
                continue
            weight = step_cost(cost, previous, current, config=config)
            if not math.isfinite(weight):
                continue
            candidate = current_distance + weight
            if candidate < distances.get(previous, math.inf):
                distances[previous] = candidate
                next_cell[previous] = current
                heapq.heappush(queue, (candidate, previous))

    return distances, next_cell


def _suffix(next_cell, start, goal, limit):
    path = [start]
    seen = {start}
    while path[-1] != goal:
        nxt = next_cell.get(path[-1])
        if nxt is None or nxt in seen or len(path) > limit:
            return None
        path.append(nxt)
        seen.add(nxt)
    return path


def second_route_segment(cost, primary, config, algorithm):
    path = list(primary.path)
    if len(path) < 2:
        raise NoRouteError("起点和终点相同，没有不同的备选路线。")

    distances, next_cell = _reverse_shortest_tree(cost, path[-1], config)
    prefix_cost = [0.0]
    for detail in primary.stats["step_details"]:
        prefix_cost.append(detail["cumulative"])

    best_path = None
    best_cost = math.inf
    limit = cost["rows"] * cost["cols"]

    for index, spur in enumerate(path[:-1]):
        root = path[:index + 1]
        root_nodes = set(root)
        primary_next = path[index + 1]

        for candidate, weight, _factor in neighbor_steps(cost, spur, config):
            if candidate == primary_next or candidate not in distances:
                continue
            suffix = _suffix(next_cell, candidate, path[-1], limit)
            if suffix is None or root_nodes.intersection(suffix):
                continue
            route = root + suffix
            if len(route) != len(set(route)) or route == path:
                continue
            estimated = prefix_cost[index] + weight + distances[candidate]
            if estimated < best_cost:
                best_cost = estimated
                best_path = route

    if best_path is None:
        raise NoRouteError("没有找到与主路线不同的可通行备选路线。")

    details = path_step_details(cost, best_path, config)
    length = sum(
        distance_factor(first, second, config)
        for first, second in zip(best_path, best_path[1:])
    )
    return PathResult(
        path=best_path,
        stats={
            "total_cost": path_total_cost(cost, best_path, config),
            "length": length,
            "steps": len(best_path) - 1,
            "expanded": 0,
            "elapsed_ms": 0.0,
            "step_details": details,
            "algorithm": algorithm + "-alternative",
        },
    )


def second_route_through(cost, segment_results, config, algorithm):
    candidates = []
    for index, primary_segment in enumerate(segment_results):
        try:
            replacement = second_route_segment(
                cost, primary_segment, config, algorithm
            )
        except NoRouteError:
            continue
        combined_segments = list(segment_results)
        combined_segments[index] = replacement
        candidates.append(
            combine_results(cost, combined_segments, config, algorithm)
        )

    if not candidates:
        raise NoRouteError("没有找到满足必经点约束的备选路线。")
    return min(
        candidates,
        key=lambda result: (
            result.stats["total_cost"],
            result.stats["length"],
        ),
    )

"""按固定种子生成成本栅格，对比两种算法的准确性与搜索速度。"""

import argparse
import json
import math
import platform
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cost_path import CostGrid, find_path


def make_grid(size, seed):
    rng = random.Random(seed + size)
    rows = []
    for row in range(size):
        values = []
        for col in range(size):
            blocked = row != 0 and col != size - 1 and rng.random() < 0.05
            values.append(None if blocked else rng.randint(1, 9))
        rows.append(values)
    return CostGrid(rows)


def make_uniform_grid(size):
    return CostGrid([[1] * size for _ in range(size)])


def main():
    parser = argparse.ArgumentParser(description="丙组 Dijkstra / A* 栅格速度对照")
    parser.add_argument("--sizes", type=int, nargs="+", default=[100, 500, 1000])
    parser.add_argument("--seed", type=int, default=20261116)
    parser.add_argument("--terrain", choices=("both", "uniform", "random"), default="both")
    parser.add_argument("--cost-mode", choices=("target", "average"), default="target")
    parser.add_argument("--no-corner-cut", action="store_true",
                        help="禁止斜向穿过障碍拐角；默认按乙组规则允许切角")
    parser.add_argument("--output", type=Path, help="可选：将结果写入 JSON 文件")
    args = parser.parse_args()
    if any(size < 2 for size in args.sizes):
        parser.error("所有 size 都必须大于 1")

    records = []
    for size in args.sizes:
        terrains = ("uniform", "random") if args.terrain == "both" else (args.terrain,)
        for terrain in terrains:
            grid = make_uniform_grid(size) if terrain == "uniform" else make_grid(size, args.seed)
            start, goal = (0, 0), (size - 1, size - 1)
            results = {}
            for algorithm in ("dijkstra", "astar"):
                result = find_path(grid, start, goal, algorithm=algorithm,
                                   cost_mode=args.cost_mode,
                                   allow_corner_cutting=not args.no_corner_cut)
                results[algorithm] = result
                record = {
                    "terrain": terrain,
                    "size": size,
                    "cells": size * size,
                    "algorithm": algorithm,
                    "total_cost": round(result.total_cost, 8),
                    "path_nodes": len(result.path_cells),
                    "expanded_nodes": result.expanded_nodes,
                    "elapsed_ms": round(result.elapsed_ms, 3),
                }
                records.append(record)
                print(json.dumps(record, ensure_ascii=False), flush=True)
            if not math.isclose(results["dijkstra"].total_cost,
                                results["astar"].total_cost, rel_tol=1e-10, abs_tol=1e-8):
                raise AssertionError("{} {}×{} 两种算法成本不一致".format(terrain, size, size))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"seed": args.seed,
                                          "cost_mode": args.cost_mode,
                                          "diagonal_factor": math.sqrt(2),
                                          "include_start": False,
                                          "allow_corner_cut": not args.no_corner_cut,
                                          "nonpositive_blocked": True,
                                          "python": sys.version.split()[0],
                                          "platform": platform.platform(),
                                          "records": records},
                                          ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

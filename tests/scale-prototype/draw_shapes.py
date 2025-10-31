import json
from pathlib import Path
from typing import Iterable, Sequence

import tkinter as tk

WINDOW_WIDTH = 1024
WINDOW_HEIGHT = 768
CONFIG_PATH = Path(__file__).with_name("landingpad.json")
SHAPES_PATH = Path(__file__).with_name("shape.json")
DEFAULT_BASE_OFFSET = (0.0, 0.0)
SCALE_POINT_DEFAULT = "NW"


def as_point(seq: Sequence[float]) -> tuple[float, float]:
    return float(seq[0]), float(seq[1])


def extract_points_from_element(element: dict) -> list[tuple[float, float]]:
    element_type = element.get("type")
    points: list[tuple[float, float]] = []

    if element_type == "square":
        points.extend(as_point(vertex) for vertex in element.get("vertices", []))
        for diagonal in element.get("diagonals", []):
            points.append(as_point(diagonal["start"]))
            points.append(as_point(diagonal["end"]))
    elif element_type == "dodecagon":
        points.extend(as_point(vertex) for vertex in element.get("vertices", []))
    elif element_type == "cross":
        for line in element.get("lines", []):
            points.append(as_point(line["start"]))
            points.append(as_point(line["end"]))
    elif element_type == "polygon" or element_type == "polyline":
        points.extend(as_point(point) for point in element.get("points", []))
    elif element_type == "rectangle":
        x = float(element.get("x", 0.0))
        y = float(element.get("y", 0.0))
        w = float(element.get("width", 0.0))
        h = float(element.get("height", 0.0))
        points.extend(
            [
                (x, y),
                (x + w, y),
                (x, y + h),
                (x + w, y + h),
            ]
        )

    return points


def compute_scale_origin(
    points: Sequence[tuple[float, float]], anchor: str
) -> tuple[float, float]:
    if not points:
        return 0.0, 0.0

    min_x = min(point[0] for point in points)
    max_x = max(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_y = max(point[1] for point in points)

    anchor_upper = anchor.upper()
    if anchor_upper == "NE":
        return max_x, min_y
    if anchor_upper == "SW":
        return min_x, max_y
    if anchor_upper == "SE":
        return max_x, max_y
    if anchor_upper == "CENTER":
        return (min_x + max_x) / 2, (min_y + max_y) / 2
    if anchor_upper == "ORIGIN":
        return 0.0, 0.0

    # Default to north-west corner.
    return min_x, min_y


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def transform_point(
    point: Sequence[float],
    scale: Sequence[float],
    pivot: Sequence[float],
    base_offset: Sequence[float],
    offset_delta: Sequence[float],
) -> tuple[float, float]:
    pivot_x, pivot_y = pivot
    scaled_x = pivot_x + (point[0] - pivot_x) * scale[0]
    scaled_y = pivot_y + (point[1] - pivot_y) * scale[1]
    return (
        scaled_x + base_offset[0] + offset_delta[0],
        scaled_y + base_offset[1] + offset_delta[1],
    )


def flatten_points(points: Iterable[tuple[float, float]]) -> list[float]:
    flat: list[float] = []
    for x, y in points:
        flat.extend([x, y])
    return flat


def main() -> None:
    config = load_config(CONFIG_PATH)
    shapes = load_config(SHAPES_PATH)
    shapes_by_name = {
        group.get("name", "Unnamed"): group.get("elements", [])
        for group in shapes.get("groups", [])
    }

    root = tk.Tk()
    root.title("Landingpad Viewer")

    canvas = tk.Canvas(root, width=WINDOW_WIDTH, height=WINDOW_HEIGHT, bg="black")
    canvas.pack()

    for group in config.get("groups", []):
        group_name = group.get("name", "Unnamed")
        scale_config = group.get("transform", {}).get("scale", {})
        scale = (
            float(scale_config.get("x", 1.0)),
            float(scale_config.get("y", 1.0)),
        )
        offset_delta = (
            float(group.get("transform", {}).get("offset", {}).get("x", 0.0)),
            float(group.get("transform", {}).get("offset", {}).get("y", 0.0)),
        )
        scale_point = str(scale_config.get("point", SCALE_POINT_DEFAULT))
        scale_point_upper = scale_point.upper()

        base_offset = DEFAULT_BASE_OFFSET
        effective_offset_delta = offset_delta

        elements = shapes_by_name.get(group_name, [])

        raw_points: list[tuple[float, float]] = []
        for element in elements:
            raw_points.extend(extract_points_from_element(element))
        pivot = compute_scale_origin(raw_points, scale_point)
        pivot_screen: tuple[float, float] | None = None
        if raw_points or scale_point_upper == "ORIGIN":
            pivot_screen = (
                pivot[0]
                + base_offset[0]
                + (0.0 if scale_point_upper == "ORIGIN" else effective_offset_delta[0]),
                pivot[1]
                + base_offset[1]
                + (0.0 if scale_point_upper == "ORIGIN" else effective_offset_delta[1]),
            )

        for element in elements:
            element_type = element.get("type")

            if element_type == "cross":
                for line in element.get("lines", []):
                    start = transform_point(
                        line["start"],
                        scale,
                        pivot,
                        base_offset,
                        effective_offset_delta,
                    )
                    end = transform_point(
                        line["end"],
                        scale,
                        pivot,
                        base_offset,
                        effective_offset_delta,
                    )
                    canvas.create_line(*start, *end, width=3, fill="black")

            elif element_type == "square":
                vertices = [
                    transform_point(
                        vertex,
                        scale,
                        pivot,
                        base_offset,
                        effective_offset_delta,
                    )
                    for vertex in element.get("vertices", [])
                ]
                if vertices:
                    canvas.create_polygon(
                        flatten_points(vertices), outline="navy", width=3, fill=""
                    )
                    label_color = element.get("label_color", "dim gray")
                    for transformed in vertices:
                        relative_x = transformed[0]
                        relative_y = transformed[1]
                        label = f"({relative_x:.1f}, {relative_y:.1f})"
                        canvas.create_text(
                            transformed[0] + 10,
                            transformed[1] - 10,
                            text=label,
                            fill=label_color,
                            anchor="sw",
                            font=("Helvetica", 10),
                        )

                for diagonal in element.get("diagonals", []):
                    start = transform_point(
                        diagonal["start"],
                        scale,
                        pivot,
                        base_offset,
                        effective_offset_delta,
                    )
                    end = transform_point(
                        diagonal["end"],
                        scale,
                        pivot,
                        base_offset,
                        effective_offset_delta,
                    )
                    canvas.create_line(*start, *end, width=2, fill="firebrick")

            elif element_type == "dodecagon":
                vertices = [
                    transform_point(
                        vertex,
                        scale,
                        pivot,
                        base_offset,
                        effective_offset_delta,
                    )
                    for vertex in element.get("vertices", [])
                ]
                if vertices:
                    canvas.create_polygon(
                        flatten_points(vertices), outline="forest green", width=2, fill=""
                    )

            elif element_type == "polygon":
                vertices = [
                    transform_point(
                        point,
                        scale,
                        pivot,
                        base_offset,
                        effective_offset_delta,
                    )
                    for point in element.get("points", [])
                ]
                if vertices:
                    outline_color = element.get("color", "black")
                    fill_color = element.get("fill") or ""
                    canvas.create_polygon(
                        flatten_points(vertices),
                        outline=outline_color,
                        fill=fill_color,
                        width=2,
                    )

            elif element_type == "polyline":
                vertices = [
                    transform_point(
                        point,
                        scale,
                        pivot,
                        base_offset,
                        effective_offset_delta,
                    )
                    for point in element.get("points", [])
                ]
                if len(vertices) >= 2:
                    color = element.get("color", "black")
                    canvas.create_line(
                        *flatten_points(vertices),
                        fill=color,
                        width=2,
                    )

            elif element_type == "rectangle":
                x1, y1 = transform_point(
                    (element.get("x", 0.0), element.get("y", 0.0)),
                    scale,
                    pivot,
                    base_offset,
                    effective_offset_delta,
                )
                x2, y2 = transform_point(
                    (
                        element.get("x", 0.0) + element.get("width", 0.0),
                        element.get("y", 0.0) + element.get("height", 0.0),
                    ),
                    scale,
                    pivot,
                    base_offset,
                    effective_offset_delta,
                )
                color = element.get("color", "black")
                fill_color = element.get("fill")
                canvas.create_rectangle(
                    x1,
                    y1,
                    x2,
                    y2,
                    outline=color,
                    fill=fill_color or "",
                )

        if pivot_screen is not None:
            radius = 5
            canvas.create_oval(
                pivot_screen[0] - radius,
                pivot_screen[1] - radius,
                pivot_screen[0] + radius,
                pivot_screen[1] + radius,
                fill="red",
                outline="",
            )
            label_text = f"({pivot_screen[0]:.1f}, {pivot_screen[1]:.1f})"
            if scale_point_upper == "ORIGIN":
                label_anchor = "nw"
                label_x = pivot_screen[0] + radius + 6
                label_y = pivot_screen[1] + radius + 6
            else:
                label_anchor = "sw"
                label_x = pivot_screen[0] + radius + 6
                label_y = pivot_screen[1] - radius - 6
            canvas.create_text(
                label_x,
                label_y,
                text=label_text,
                fill="red",
                anchor=label_anchor,
                font=("Helvetica", 10, "bold"),
            )

    root.mainloop()


if __name__ == "__main__":
    main()

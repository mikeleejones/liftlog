"""SVG line-chart geometry per docs/design.md: single violet series, 2px
stroke, no fills, mono muted axis labels, dots only on PR points, deload
weeks as muted dashed segments. Geometry computed here; the SVG is rendered
in the template from this dict."""

PAD_L = 44   # room for y labels
PAD_R = 12
PAD_T = 12
PAD_B = 24   # room for x labels


def line_chart(points, width=680, height=240):
    """points: [{'value': float, 'is_pr': bool, 'is_deload': bool,
    'label': str}] in chronological order. Returns geometry or None if there
    is nothing plottable."""
    if not points:
        return None

    values = [p["value"] for p in points]
    vmin, vmax = min(values), max(values)
    if vmax == vmin:
        # flat series: pad so the line sits mid-height
        vmin -= 1
        vmax += 1

    plot_w = width - PAD_L - PAD_R
    plot_h = height - PAD_T - PAD_B

    def x_at(i):
        if len(points) == 1:
            return PAD_L + plot_w / 2
        return PAD_L + plot_w * i / (len(points) - 1)

    def y_at(v):
        return PAD_T + plot_h * (1 - (v - vmin) / (vmax - vmin))

    coords = [(x_at(i), y_at(p["value"])) for i, p in enumerate(points)]

    segments = []
    for i in range(len(coords) - 1):
        deload = points[i]["is_deload"] or points[i + 1]["is_deload"]
        segments.append({
            "x1": round(coords[i][0], 1), "y1": round(coords[i][1], 1),
            "x2": round(coords[i + 1][0], 1), "y2": round(coords[i + 1][1], 1),
            "deload": deload,
        })

    dots = [
        {"x": round(coords[i][0], 1), "y": round(coords[i][1], 1)}
        for i, p in enumerate(points) if p["is_pr"]
    ]

    # a single point has no segment to draw, so always mark it
    if len(points) == 1:
        dots = [{"x": round(coords[0][0], 1), "y": round(coords[0][1], 1)}]

    def fmt(v):
        return f"{round(v, 1):g}"

    y_labels = [
        {"y": round(y_at(vmax), 1), "text": fmt(vmax)},
        {"y": round(y_at(vmin), 1), "text": fmt(vmin)},
    ]
    x_labels = [
        {"x": round(coords[0][0], 1), "text": points[0]["label"], "anchor": "start"},
    ]
    if len(points) > 1:
        x_labels.append(
            {"x": round(coords[-1][0], 1), "text": points[-1]["label"], "anchor": "end"}
        )

    return {
        "width": width,
        "height": height,
        "segments": segments,
        "dots": dots,
        "y_labels": y_labels,
        "x_labels": x_labels,
        "baseline_y": round(PAD_T + plot_h, 1),
        "left_x": PAD_L,
        "right_x": width - PAD_R,
    }

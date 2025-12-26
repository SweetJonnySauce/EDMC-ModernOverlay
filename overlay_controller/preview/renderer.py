from __future__ import annotations

from typing import Optional, Tuple

from overlay_controller.preview import snapshot_math


class PreviewRenderer:
    """Draws the placement preview onto a Tk canvas."""

    def __init__(self, canvas, *, padding: int = 10, abs_width: float = 1280.0, abs_height: float = 960.0) -> None:
        self.canvas = canvas
        self.padding = padding
        self.abs_width = abs_width
        self.abs_height = abs_height
        self._last_signature: Tuple[object, ...] | None = None

    def draw(
        self,
        selection: tuple[str, str] | None,
        snapshot,
        *,
        live_anchor_token: Optional[str],
        scale_mode_value: str,
        resolve_target_frame,
        compute_anchor_point,
    ) -> None:
        canvas = self.canvas
        if canvas is None:
            return
        width = int(canvas.winfo_width() or canvas["width"])
        height = int(canvas.winfo_height() or canvas["height"])
        padding = self.padding
        inner_w = max(1, width - 2 * padding)
        inner_h = max(1, height - 2 * padding)

        preview_bounds: tuple[float, float, float, float] | None = None
        preview_anchor_token: str | None = None
        preview_anchor_abs: tuple[float, float] | None = None
        if snapshot is not None:
            snapshot = snapshot_math.translate_snapshot_for_fill(
                snapshot,
                inner_w,
                inner_h,
                scale_mode_value=scale_mode_value,
                anchor_token_override=live_anchor_token,
            )
            target_frame = resolve_target_frame(snapshot)
            if target_frame is not None:
                bounds, anchor_point = target_frame
                preview_bounds = bounds
                preview_anchor_token = live_anchor_token
                preview_anchor_abs = anchor_point
            else:
                bounds = snapshot.transform_bounds or snapshot.base_bounds
                preview_bounds = bounds
                preview_anchor_token = snapshot.transform_anchor_token or snapshot.anchor_token
                preview_anchor_abs = compute_anchor_point(
                    bounds[0],
                    bounds[2],
                    bounds[1],
                    bounds[3],
                    preview_anchor_token,
                )

        signature_snapshot = (
            snapshot.base_bounds if snapshot is not None else None,
            snapshot.transform_bounds if snapshot is not None else None,
            snapshot.anchor_token if snapshot is not None else None,
            snapshot.transform_anchor_token if snapshot is not None else None,
            snapshot.offset_x if snapshot is not None else None,
            snapshot.offset_y if snapshot is not None else None,
            snapshot.cache_timestamp if snapshot is not None else None,
            getattr(snapshot, "background_color", None) if snapshot is not None else None,
            getattr(snapshot, "background_border_color", None) if snapshot is not None else None,
            getattr(snapshot, "background_border_width", None) if snapshot is not None else None,
        )
        current_signature = (
            width,
            height,
            padding,
            selection,
            signature_snapshot,
            preview_bounds,
            preview_anchor_abs,
        )
        if self._last_signature == current_signature:
            return
        self._last_signature = current_signature

        canvas.delete("all")
        if selection is None:
            canvas.create_text(width // 2, height // 2, text="(select a group)", fill="#888888")
            return
        if snapshot is None:
            canvas.create_text(width // 2, height // 2, text="(awaiting cache)", fill="#888888")
            return

        label = selection[1]
        base_min_x, base_min_y, base_max_x, base_max_y = snapshot.base_bounds
        preview_bounds = preview_bounds or (snapshot.transform_bounds or snapshot.base_bounds)
        trans_min_x, trans_min_y, trans_max_x, trans_max_y = preview_bounds
        preview_anchor_token = preview_anchor_token or snapshot.transform_anchor_token or snapshot.anchor_token

        scale = max(0.01, min(inner_w / float(self.abs_width), inner_h / float(self.abs_height)))
        content_w = self.abs_width * scale
        content_h = self.abs_height * scale
        offset_x = padding + max(0.0, (inner_w - content_w) / 2.0)
        offset_y = padding + max(0.0, (inner_h - content_h) / 2.0)

        canvas.create_rectangle(
            offset_x,
            offset_y,
            offset_x + content_w,
            offset_y + content_h,
            outline="#555555",
            dash=(3, 3),
        )

        def _rect_color(fill: str) -> dict[str, object]:
            return {"fill": fill, "outline": "#000000", "width": 1}

        norm_x0 = offset_x + base_min_x * scale
        norm_y0 = offset_y + base_min_y * scale
        norm_x1 = offset_x + base_max_x * scale
        norm_y1 = offset_y + base_max_y * scale
        canvas.create_rectangle(norm_x0, norm_y0, norm_x1, norm_y1, **_rect_color("#66a3ff"))
        label_text = "Original Placement"
        label_font = ("TkDefaultFont", 8, "bold")
        inside = (norm_x1 - norm_x0) >= 110 and (norm_y1 - norm_y0) >= 20
        label_fill = "#ffffff" if not inside else "#1c2b4a"
        label_x = norm_x0 + 4 if inside else norm_x1 + 6
        label_y = norm_y0 + 12 if inside else norm_y0
        canvas.create_text(
            label_x,
            label_y,
            text=label_text,
            anchor="nw",
            fill=label_fill,
            font=label_font,
        )

        trans_x0 = offset_x + trans_min_x * scale
        trans_y0 = offset_y + trans_min_y * scale
        trans_x1 = offset_x + trans_max_x * scale
        trans_y1 = offset_y + trans_max_y * scale
        bg_color = getattr(snapshot, "background_color", None)
        bg_border_color = getattr(snapshot, "background_border_color", None)
        bg_border = getattr(snapshot, "background_border_width", 0) if snapshot is not None else 0
        expand = max(0.0, float(bg_border or 0) * scale)
        fill_left = trans_x0 - expand
        fill_top = trans_y0 - expand
        fill_right = trans_x1 + expand
        fill_bottom = trans_y1 + expand

        if bg_color:
            tk_color = bg_color[:7] if isinstance(bg_color, str) and len(bg_color) == 9 else bg_color
            try:
                canvas.create_rectangle(
                    fill_left,
                    fill_top,
                    fill_right,
                    fill_bottom,
                    fill=tk_color,
                    outline="",
                )
            except Exception:
                pass
        if bg_border_color:
            tk_border = (
                bg_border_color[:7]
                if isinstance(bg_border_color, str) and len(bg_border_color) == 9
                else bg_border_color
            )
            stroke = 1.0
            left = fill_left - stroke
            top = fill_top - stroke
            right = fill_right + stroke
            bottom = fill_bottom + stroke
            try:
                canvas.create_rectangle(left, top, right, fill_top, fill=tk_border, outline="")
                canvas.create_rectangle(left, fill_bottom, right, bottom, fill=tk_border, outline="")
                canvas.create_rectangle(left, fill_top, fill_left, fill_bottom, fill=tk_border, outline="")
                canvas.create_rectangle(fill_right, fill_top, right, fill_bottom, fill=tk_border, outline="")
            except Exception:
                pass
        canvas.create_rectangle(trans_x0, trans_y0, trans_x1, trans_y1, **_rect_color("#ffa94d"))
        actual_label = "Target Placement"
        actual_inside = (trans_x1 - trans_x0) >= 110 and (trans_y1 - trans_y0) >= 20
        actual_fill = "#ffffff" if not actual_inside else "#5a2d00"
        actual_label_x = trans_x0 + 4 if actual_inside else trans_x1 + 6
        actual_label_y = trans_y0 + 12 if actual_inside else trans_y0
        canvas.create_text(
            actual_label_x,
            actual_label_y,
            text=actual_label,
            anchor="nw",
            fill=actual_fill,
            font=("TkDefaultFont", 8, "bold"),
        )

        if preview_anchor_abs is not None:
            anchor_px, anchor_py = preview_anchor_abs
            anchor_screen_x = offset_x + anchor_px * scale
            anchor_screen_y = offset_y + anchor_py * scale
            anchor_radius = 4
            canvas.create_oval(
                anchor_screen_x - anchor_radius,
                anchor_screen_y - anchor_radius,
                anchor_screen_x + anchor_radius,
                anchor_screen_y + anchor_radius,
                fill="#ffffff",
                outline="#000000",
                width=1,
            )

        canvas.create_text(
            padding + 6,
            padding + 6,
            text=f"{label}",
            anchor="nw",
            fill="#ffffff",
            font=("TkDefaultFont", 9, "bold"),
        )

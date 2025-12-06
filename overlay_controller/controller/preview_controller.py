from __future__ import annotations

import json
import time

from overlay_controller.preview.renderer import PreviewRenderer
from overlay_controller.services.group_state import GroupSnapshot


class PreviewController:
    """Owns preview orchestration: snapshot refresh, target frame resolution, and rendering."""

    def __init__(self, app, *, abs_width: float, abs_height: float, padding: int) -> None:
        self.app = app
        self.abs_width = abs_width
        self.abs_height = abs_height
        self.padding = padding
        self._renderer: PreviewRenderer | None = None
        self._snapshots: dict[tuple[str, str], GroupSnapshot] = {}

    @property
    def snapshots(self) -> dict[tuple[str, str], GroupSnapshot]:
        return self._snapshots

    def scale_mode_setting(self) -> str:
        try:
            raw = json.loads(self.app._settings_path.read_text(encoding="utf-8"))
            value = raw.get("scale_mode")
            if isinstance(value, str):
                token = value.strip().lower()
                if token in {"fit", "fill"}:
                    return token
        except Exception:
            pass
        return "fill"

    def refresh_current_group_snapshot(self, force_ui: bool = True) -> None:
        selection = self.app._get_current_group_selection()
        if selection is None:
            self.app._set_group_controls_enabled(False)
            self.update_absolute_widget_color(None)
            self.draw_preview()
            return

        plugin_name, label = selection

        now = time.time()
        timers = getattr(self.app, "_mode_timers", None)
        live_edit_active = False
        if timers is not None:
            try:
                live_edit_active = bool(timers.live_edit_active())
            except Exception:
                live_edit_active = False
        if live_edit_active or now < getattr(self.app, "_offset_live_edit_until", 0.0):
            snapshot = self._snapshots.get(selection)
            if snapshot is not None:
                self.app._set_group_controls_enabled(True)
                self.apply_snapshot_to_absolute_widget(selection, snapshot, force_ui=force_ui)
                self.update_absolute_widget_color(snapshot)
                self.draw_preview()
                return

        snapshot = self.build_group_snapshot(plugin_name, label)
        if snapshot is None:
            self._snapshots.pop(selection, None)
            self.app._set_group_controls_enabled(False)
            self.update_absolute_widget_color(None)
            self.draw_preview()
            return

        self._snapshots[selection] = snapshot
        self.app._set_group_controls_enabled(True)
        self.apply_snapshot_to_absolute_widget(selection, snapshot, force_ui=force_ui)
        self.update_absolute_widget_color(snapshot)
        self.draw_preview()

    def get_group_snapshot(self, selection: tuple[str, str] | None = None) -> GroupSnapshot | None:
        key = selection if selection is not None else self.app._get_current_group_selection()
        if key is None:
            return None
        return self._snapshots.get(key)

    def update_absolute_widget_color(self, snapshot: GroupSnapshot | None) -> None:
        widget = getattr(self.app, "absolute_widget", None)
        if widget is None:
            return
        try:
            widget.set_text_color(None)
        except Exception:
            pass
        self.app._update_contextual_tip()

    def apply_snapshot_to_absolute_widget(
        self, selection: tuple[str, str], snapshot: GroupSnapshot, *, force_ui: bool = True
    ) -> None:
        if not hasattr(self.app, "absolute_widget"):
            return
        abs_x, abs_y = self.compute_absolute_from_snapshot(snapshot)
        self.app._store_absolute_state(selection, abs_x, abs_y)
        widget = getattr(self.app, "absolute_widget", None)
        if widget is None:
            return
        if force_ui:
            try:
                widget.set_px_values(abs_x, abs_y)
            except Exception:
                pass

    def draw_preview(self) -> None:
        renderer = self._renderer
        if renderer is None:
            canvas = getattr(self.app, "preview_canvas", None)
            if canvas is None:
                return
            renderer = PreviewRenderer(
                canvas,
                padding=self.padding,
                abs_width=self.abs_width,
                abs_height=self.abs_height,
            )
            self._renderer = renderer
            try:
                self.app._preview_renderer = renderer
            except Exception:
                pass

        selection = self.app._get_current_group_selection()
        snapshot = self.get_group_snapshot(selection) if selection is not None else None
        renderer.draw(
            selection,
            snapshot,
            live_anchor_token=self.get_live_anchor_token(snapshot) if snapshot is not None else None,
            scale_mode_value=self.scale_mode_setting(),
            resolve_target_frame=self.resolve_target_frame,
            compute_anchor_point=self.compute_anchor_point,
        )
        try:
            self.app._last_preview_signature = renderer._last_signature  # type: ignore[attr-defined]
        except Exception:
            pass

    def get_live_anchor_token(self, snapshot: GroupSnapshot) -> str:
        anchor_widget = getattr(self.app, "anchor_widget", None)
        anchor_name: str | None = None
        if anchor_widget is not None:
            getter = getattr(anchor_widget, "get_anchor", None)
            if callable(getter):
                try:
                    anchor_name = getter()
                except Exception:
                    anchor_name = None
        return (anchor_name or snapshot.anchor_token or "nw").strip().lower()

    def get_live_absolute_anchor(self, snapshot: GroupSnapshot) -> tuple[float, float]:
        default_x, default_y = self.compute_absolute_from_snapshot(snapshot)
        abs_widget = getattr(self.app, "absolute_widget", None)
        if abs_widget is None:
            return default_x, default_y

        try:
            user_x, user_y = abs_widget.get_px_values()
        except Exception:
            user_x = user_y = None

        resolved_x = default_x if user_x is None else self.app._clamp_absolute_value(float(user_x), "x")
        resolved_y = default_y if user_y is None else self.app._clamp_absolute_value(float(user_y), "y")
        return resolved_x, resolved_y

    def get_target_dimensions(self, snapshot: GroupSnapshot) -> tuple[float, float]:
        bounds = snapshot.transform_bounds or snapshot.base_bounds
        min_x, min_y, max_x, max_y = bounds
        width = max(0.0, float(max_x - min_x))
        height = max(0.0, float(max_y - min_y))
        return width, height

    def bounds_from_anchor_point(
        self, anchor: str, anchor_x: float, anchor_y: float, width: float, height: float
    ) -> tuple[float, float, float, float]:
        width = max(width, 0.0)
        height = max(height, 0.0)
        horizontal, vertical = self.app._anchor_sides(anchor)

        if horizontal == "left":
            min_x = anchor_x
            max_x = anchor_x + width
        elif horizontal == "right":
            max_x = anchor_x
            min_x = anchor_x - width
        else:
            min_x = anchor_x - (width / 2.0)
            max_x = min_x + width

        if vertical == "top":
            min_y = anchor_y
            max_y = anchor_y + height
        elif vertical == "bottom":
            max_y = anchor_y
            min_y = anchor_y - height
        else:
            min_y = anchor_y - (height / 2.0)
            max_y = min_y + height

        return min_x, min_y, max_x, max_y

    def resolve_target_frame(self, snapshot: GroupSnapshot):
        width, height = self.get_target_dimensions(snapshot)
        if width <= 0.0 or height <= 0.0:
            return None
        anchor_token = self.get_live_anchor_token(snapshot)
        anchor_x, anchor_y = self.get_live_absolute_anchor(snapshot)
        bounds = self.bounds_from_anchor_point(anchor_token, anchor_x, anchor_y, width, height)
        return bounds, (anchor_x, anchor_y)

    def compute_absolute_from_snapshot(self, snapshot: GroupSnapshot) -> tuple[float, float]:
        base_min_x, base_min_y, _, _ = snapshot.base_bounds
        return base_min_x + snapshot.offset_x, base_min_y + snapshot.offset_y

    def build_group_snapshot(self, plugin_name: str, label: str) -> GroupSnapshot | None:
        state = getattr(self.app, "_group_state", None)
        if state is not None:
            try:
                return state.snapshot(plugin_name, label)
            except Exception:
                return None

        cfg = self.app._get_group_config(plugin_name, label)
        base_payload, transformed_payload, cache_ts = self.app._get_cache_record(plugin_name, label)
        if base_payload is None:
            return None

        anchor_token = str(
            cfg.get("idPrefixGroupAnchor")
            or (transformed_payload.get("anchor") if transformed_payload else "nw")
            or "nw"
        ).lower()
        transform_anchor_token = str(
            transformed_payload.get("anchor", anchor_token) if isinstance(transformed_payload, dict) else anchor_token
        ).lower()
        offset_x = float(cfg.get("offsetX", 0.0)) if isinstance(cfg, dict) else 0.0
        offset_y = float(cfg.get("offsetY", 0.0)) if isinstance(cfg, dict) else 0.0
        base_min_x = float(base_payload.get("base_min_x", 0.0))
        base_min_y = float(base_payload.get("base_min_y", 0.0))
        base_max_x = float(base_payload.get("base_max_x", base_min_x))
        base_max_y = float(base_payload.get("base_max_y", base_min_y))
        base_bounds = (base_min_x, base_min_y, base_max_x, base_max_y)
        base_anchor = self.compute_anchor_point(base_min_x, base_max_x, base_min_y, base_max_y, anchor_token)

        trans_min_x = base_min_x + offset_x
        trans_min_y = base_min_y + offset_y
        trans_max_x = base_max_x + offset_x
        trans_max_y = base_max_y + offset_y
        transform_bounds = (trans_min_x, trans_min_y, trans_max_x, trans_max_y)
        transform_anchor = self.compute_anchor_point(
            trans_min_x, trans_max_x, trans_min_y, trans_max_y, transform_anchor_token
        )

        return GroupSnapshot(
            plugin=plugin_name,
            label=label,
            anchor_token=anchor_token,
            transform_anchor_token=transform_anchor_token,
            offset_x=offset_x,
            offset_y=offset_y,
            base_bounds=base_bounds,
            base_anchor=base_anchor,
            transform_bounds=transform_bounds,
            transform_anchor=transform_anchor,
            has_transform=True,
            cache_timestamp=cache_ts,
        )

    def compute_anchor_point(
        self, min_x: float, max_x: float, min_y: float, max_y: float, anchor: str
    ) -> tuple[float, float]:
        h, v = self.app._anchor_sides(anchor)
        ax = min_x if h == "left" else max_x if h == "right" else (min_x + max_x) / 2.0
        ay = min_y if v == "top" else max_y if v == "bottom" else (min_y + max_y) / 2.0
        return ax, ay

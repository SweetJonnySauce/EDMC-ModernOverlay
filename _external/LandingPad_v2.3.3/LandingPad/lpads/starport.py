import math

import tkinter as tk

from .base import LandingPads
from .misc import round_away, calc_aspect_x


class StarportPads(LandingPads):

    pad_list = [
        (0,0), (0,0), (0,2), (0,2),
        (1,0), (1,0), (1,1), (1,2),
        (2,0), (2,2),
        (3,0), (3,0), (3,1), (3,2), (3,2),
    ]
    shell_scale = (1, 0.625, 0.455, 0.25)

    def calc_values(self):
        self.alpha = math.radians(15)
        self.sin15 = math.sin(self.alpha)
        self.cos15 = math.cos(self.alpha)
        self.sin45 = math.sqrt(2) / 2
        self.sin60 = math.sqrt(3) / 2
        self.dodecagon = [
            (+self.cos15, -self.sin15),
            (+self.sin45, -self.sin45),
            (+self.sin15, -self.cos15),
            (-self.sin15, -self.cos15),
            (-self.sin45, -self.sin45),
            (-self.cos15, -self.sin15),
            (-self.cos15, +self.sin15),
            (-self.sin45, +self.sin45),
            (-self.sin15, +self.cos15),
            (+self.sin15, +self.cos15),
            (+self.sin45, +self.sin45),
            (+self.cos15, +self.sin15),
        ]
        self.pad_sectors = [
            ( 0, +1), (-0.5, +self.sin60), (-self.sin60, +0.5),
            (-1,  0), (-self.sin60, -0.5), (-0.5, -self.sin60),
            ( 0, -1), (+0.5, -self.sin60), (+self.sin60, -0.5),
            (+1,  0), (+self.sin60, +0.5), (+0.5, +self.sin60),
        ]

    def get_poly_points(self, cx, cy, r):
        return [
            (
                cx + round_away(dx*r),
                cy + round_away(dy*r),
            )
            for (dx, dy) in self.dodecagon
        ]

    def get_toaster(self, r, s=0):
        dx = round_away(r * 0.75)
        dy = round_away(r * self.shell_scale[-1])
        dr = round_away(dy * 0.08)
        toaster = [
            (+0,     -dy-s),
            (+dx-dr, -dy-s),
            (+dx+dr, -dy+2*dr-s),
            (+r-dr,  -dy+2*dr-s),
            (+r-s,   -dy+3*dr-s),
            (+r-s,   +dy-3*dr+s),
            (+r-dr,  +dy-2*dr+s),
            (+dx+dr, +dy-2*dr+s),
            (+dx-dr, +dy+s),
            (+0,     +dy+s),
        ]
        return toaster

    def draw_station(self):
        # redraw
        self.delete("all")
        self.pad_obj = None
        self.stn_obj = False
        self.centerX = centerX = int(self.width/2 + 0.5)
        self.centerY = centerY = int(self.height/2 + 0.5)
        minval = min(centerX, centerY)
        strong = 4 - (minval < 250) - (minval < 150) - (minval < 50)
        self.radiusP = radiusP = minval - strong

        strong = 4 - (radiusP < 250) - (radiusP < 150) - (radiusP < 50)
        shellList = []
        lenScale = len(self.shell_scale)
        for p, scale in enumerate(self.shell_scale):
            r = radiusP * scale
            polyPoints = self.get_poly_points(centerX, centerY, r)
            if 0 < p < lenScale-1:
                lw = max(1, strong-1)
            else:
                lw = strong
            self.create_polygon(*polyPoints, width=lw, outline=self.col_stn, fill='', joinstyle=tk.ROUND)
            shellList.append(polyPoints)

        for (x1, y1), (x2, y2) in zip(shellList[0], shellList[-1]):
            self.create_line(x1, y1, x2, y2, width=strong, fill=self.col_stn, capstyle=tk.ROUND)

        toaster = self.get_toaster(radiusP)
        green = "red" if self.backward else "green"
        red = "green" if self.backward else "red"
        self.create_line(*[(centerX+dx, centerY+dy) for (dx, dy) in toaster],width=2*strong,fill=green,capstyle=tk.BUTT, joinstyle=tk.ROUND)
        self.create_line(*[(centerX-dx, centerY+dy) for (dx, dy) in toaster],width=2*strong,fill=red,capstyle=tk.BUTT, joinstyle=tk.ROUND)
        self.stn_obj = True

    def get_pad_coords(self, pad):
        pad %= 45
        s, t = self.pad_list[pad % 15]
        s += int(pad / 15) * 4
        return (s, t)

    def draw_pad(self, pad):
        if self.pad_obj:
            self.delete(self.pad_obj)
            self.pad_obj = None
        if not self.stn_obj:
            self.draw_station()
        self.cur_pad = pad
        if pad:
            if isinstance(pad, tuple):
                s, t = pad
            else:
                s, t = self.get_pad_coords(pad-1)
                if self.backward:
                    s = (s+6) % 12
            dx, dy = self.pad_sectors[s]
            dot = self.radiusP * (self.shell_scale[0] - self.shell_scale[1]) / 4
            td = (self.shell_scale[t] + self.shell_scale[t+1]) / 2
            ov = dot * (3-t) / (4-t)
            rt = self.radiusP * self.cos15 * td
            rx = self.centerX + round_away(rt*dx)
            ry = self.centerY + round_away(rt*dy)
            self.pad_obj = self.create_oval(rx-ov, ry-ov, rx+ov, ry+ov, fill=self.col_pad)


class StarportPadsOverlay():

    id_list_pad: list = []
    id_list_toaster: list = []
    id_list_station: list = []
    config_attr_set = {
        "overlay", "backward", "radius", "center_x", "center_y", "ms_delay",
        "color_stn", "color_pad", "ttl", "cur_pad", "starport_canvas",
    }

    def __init__(
            self, overlay, backward, radius, center_x, center_y, screen_w, screen_h,
            ms_delay, color_stn, color_pad, ttl, cur_pad, starport_canvas,
    ):
        self.overlay = overlay
        self.backward = backward
        self.radius = radius
        self.center_x = center_x
        self.center_y = center_y
        self.aspect_x = calc_aspect_x(screen_w, screen_h)
        self.ms_delay = ms_delay
        self.color_stn = color_stn
        self.color_pad = color_pad
        self.ttl = ttl
        self.cur_pad = cur_pad
        self.starport_canvas = starport_canvas
        self.show = False

    def aspect(self, x):
        return round_away(self.aspect_x * x)

    def config(self, **kwargs):
        for attr_name in (self.config_attr_set & kwargs.keys()):
            setattr(self, attr_name, kwargs[attr_name])

        if all(val in kwargs for val in ("screen_w", "screen_h")):
            self.aspect_x = calc_aspect_x(kwargs["screen_w"], kwargs["screen_h"])

        if self.show:
            if len(kwargs) == 1 and "cur_pad" in kwargs:
                # redraw pad only
                self.draw_overlay_pad(self.cur_pad)
            else:
                # redraw station with a very small delay
                old_ms_delay = self.ms_delay
                self.ms_delay = min(old_ms_delay, 5)
                self.hide_overlay()
                self.show_overlay()
                self.ms_delay = old_ms_delay

    def draw_overlay_station(self):
        # draw dodecagons
        if not self.overlay:
            return
        for p, scale in enumerate(self.starport_canvas.shell_scale):
            r = self.radius * scale
            polyPoints = self.starport_canvas.get_poly_points(self.center_x, self.center_y, r)
            vectorShell = [
                {
                    "x": self.aspect(x),
                    "y": y,
                }
                for (x, y) in polyPoints + [polyPoints[0]]
            ]
            msg = {
                "id": "shell-%d" % p,
                "color": self.color_stn,
                "shape": "vect",
                "ttl": self.ttl,
                "vector": vectorShell
            }
            self.id_list_station.append(msg["id"])
            self.overlay.send_raw(msg, delay=self.ms_delay)

        # draw sector lines
        vectorFrom = self.starport_canvas.get_poly_points(self.center_x, self.center_y, self.radius * self.starport_canvas.shell_scale[0])
        vectorTo = self.starport_canvas.get_poly_points(self.center_x, self.center_y, self.radius * self.starport_canvas.shell_scale[-1])
        for l, ((x1, y1), (x2, y2)) in enumerate(zip(vectorFrom, vectorTo)):
            msg = {
                "id": "line-%d" % l,
                "color": self.color_stn,
                "shape": "vect",
                "ttl": self.ttl,
                "vector": [
                    {
                        "x": self.aspect(x1),
                        "y": y1,
                    },
                    {
                        "x": self.aspect(x2),
                        "y": y2,
                    },
                ]
            }
            self.id_list_station.append(msg["id"])
            self.overlay.send_raw(msg, delay=self.ms_delay)

    def draw_overlay_toaster(self):
        # draw toaster
        for ds in range(2):
            toaster = self.starport_canvas.get_toaster(self.radius, s=ds)
            vectorRight = [{"x": self.aspect(self.center_x+dx), "y": self.center_y+dy} for (dx, dy) in toaster]
            vectorLeft = [{"x": self.aspect(self.center_x-dx), "y": self.center_y+dy} for (dx, dy) in toaster]
            colorRight = "red" if self.backward else "green"
            colorLeft = "green" if self.backward else "red"
            for (id, color, vector) in [
                (f"toaster-right-{ds}", colorRight, vectorRight),
                (f"toaster-left-{ds}", colorLeft, vectorLeft),
            ]:
                msg = {
                    "id": id,
                    "color": color,
                    "shape": "vect",
                    "ttl": self.ttl,
                    "vector": vector
                }
                self.id_list_toaster.append(msg["id"])
                self.overlay.send_raw(msg, delay=self.ms_delay)

    def draw_overlay_pad(self, pad):
        if len(self.id_list_pad) > 0:
            for gfxID in reversed(self.id_list_pad):
                self.overlay.send_raw({"id": gfxID, "ttl": 0}, delay=self.ms_delay)
            del self.id_list_pad[:]
        self.cur_pad = pad
        if not self.cur_pad:
            return

        s, t = self.starport_canvas.get_pad_coords(pad-1)
        if self.backward:
            s = (s+6) % 12
        dx, dy = self.starport_canvas.pad_sectors[s]
        rt = self.radius * (self.starport_canvas.shell_scale[t] + self.starport_canvas.shell_scale[t+1]) / 2
        rt = rt * self.starport_canvas.cos15
        rx = self.center_x + round_away(rt*dx)
        ry = self.center_y + round_away(rt*dy)
        for i, (px, py) in enumerate([(3, 9), (7, 7), (9, 3)]):
            x = rx - px // 2
            y = ry - py // 2
            msg = {
                "id": f"pad-{pad}-{i}",
                "shape": "rect",
                "color": self.color_pad,
                "fill": self.color_pad,
                "ttl": self.ttl,
                "x": self.aspect(x),
                "y": y,
                "w": self.aspect(px),
                "h": py,
            }
            self.id_list_pad.append(msg["id"])
            self.overlay.send_raw(msg, delay=self.ms_delay)

    def hide_overlay(self):
        if self.show and self.overlay:
            for del_list in (self.id_list_pad, self.id_list_toaster, self.id_list_station):
                for gfxID in reversed(del_list):
                    self.overlay.send_raw({"id": gfxID, "ttl": 0}, delay=self.ms_delay)
                del del_list[:]
            self.show = False

    def show_overlay(self):
        if self.overlay:
            self.draw_overlay_station()
            self.draw_overlay_toaster()
            self.draw_overlay_pad(self.cur_pad)
            self.show = True

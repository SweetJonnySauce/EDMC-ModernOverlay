# -*- coding: utf-8 -*-
#
# Display the "LandigPad" position for Starports.
#

import logging
import os

import tkinter as tk
from tkinter import ttk

import myNotebook as nb
from ttkHyperlinkLabel import HyperlinkLabel
from config import appname, config

from lpads import (
    Overlay, StarportPads, StarportPadsOverlay, FleetCarrierPads, FleetCarrierPadsOverlay
)


PLUGIN_NAME = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f"{appname}.{PLUGIN_NAME}")

__version_info__ = (2, 3, 3)
__version__ = ".".join(map(str, __version_info__))

PLUGIN_URL = 'https://github.com/bgol/LandingPad'
PREFSNAME_BACKWARD = "landingpad_backward"
PREFSNAME_MAX_WIDTH = "landingpad_max_width"
PREFSNAME_HIDE_CANVAS = "landingpad_hide_canvas"
PREFSNAME_STN_OVERLAY = "landingpad_stn_overlay"
PREFSNAME_COL_OVERLAY = "landingpad_col_overlay"
PREFSNAME_SCR_OVERLAY = "landingpad_scr_overlay"
PREFSNAME_USE_OVERLAY = "landingpad_use_overlay"
PREFSNAME_MS_DELAY = "landingpad_ms_delay"
OPTIONS_GREENSIDE = ["right", "left"]
MAX_WIDTH_MINIMUM = 150

class This():
    """For holding module globals"""
    # general settings
    col_stn: str = "black"
    col_pad: str = "blue"
    backward: bool = False
    max_width: int = 0
    use_canvas: bool = True

    # EDMC Overlay settings
    use_overlay: bool = False
    over_radius: int = 100
    over_center_x: int = 100
    over_center_y: int = 490
    over_ms_delay: int = 100
    over_color_stn: str = "#ffffff"
    over_color_pad: str = "yellow"
    over_ttl: int = 10*60

    # other used globals
    curr_show: bool = None
    hide_events: set[str] = {'Docked', 'DockingCancelled', 'DockingTimeout', 'StartJump', 'Shutdown'}
    starport_types: set[str] = {'bernal', 'coriolis', 'orbis', 'asteroidbase', 'ocellus'}
    fleetcarrier_types: set[str] = {'fleetcarrier'}
    curr_station_type: str | None = None
    TYPE_STARPORT: str = "starport"
    TYPE_FLEETCARRIER: str = "fleetcarrier"

    # GUI elements
    starport_frame: tk.Frame = None
    fleetcarrier_frame: tk.Frame = None
    dummy: tk.Frame = None
    starport_canvas: StarportPads = None
    fleetcarrier_canvas: FleetCarrierPads = None
    greenside: tk.StringVar = None
    prefs_max_width: tk.IntVar = None
    prefs_hide_canvas: tk.BooleanVar = None
    overlay: Overlay | None = None
    starport_overlay: StarportPadsOverlay = None
    fleetcarrier_overlay: FleetCarrierPadsOverlay = None
    prefs_radius: tk.IntVar = None
    prefs_center_x: tk.IntVar = None
    prefs_center_y: tk.IntVar = None
    prefs_screen_w: tk.IntVar = None
    prefs_screen_h: tk.IntVar = None
    prefs_use_over: tk.BooleanVar = None
    prefs_ms_delay: tk.IntVar = None

    def __str__(self) -> str:
        return ("\n".join(line for line in ("",
            f"{self.col_stn = }",
            f"{self.col_pad = }",
            f"{self.backward = }",
            f"{self.max_width = }",
            f"{self.use_canvas = }",
            f"{self.use_overlay = }",
            f"{self.over_radius = }",
            f"{self.over_center_x = }",
            f"{self.over_center_y = }",
            f"{self.over_ms_delay = }",
            f"{self.over_color_stn = }",
            f"{self.over_color_pad = }",
            f"{self.over_ttl = }",
            f"{self.hide_events = }",
            f"{self.starport_types = }",
            f"{self.fleetcarrier_types = }",
            f"{self.curr_station_type = }",
        )))

this = This()

# For compatibility with pre-5.0.0
if not hasattr(config, "get_int"):
    config.get_int = config.getint
if not hasattr(config, 'get_bool'):
    config.get_bool = lambda key, default=False: bool(config.getint(key))
if not hasattr(config, "get_str"):
    config.get_str = config.get

def frame_resize(event):
    # reset the grid settings for the frame
    event.widget.grid(sticky=tk.EW)
    this.starport_canvas.config(width=event.width, height=event.width)
    this.fleetcarrier_canvas.config(width=event.width, height=event.width)

def show_canvas():
    if this.use_canvas:
        if this.curr_station_type == this.TYPE_STARPORT:
            this.starport_frame.grid()
        elif this.curr_station_type == this.TYPE_FLEETCARRIER:
            this.fleetcarrier_frame.grid()
        this.dummy.grid_remove()

def hide_canvas():
    this.starport_frame.grid_remove()
    this.fleetcarrier_frame.grid_remove()
    this.dummy.grid()

def show_overlay():
    if this.overlay is None and this.use_overlay:
        try_overlay()
        this.starport_overlay.config(overlay=this.overlay)
        this.fleetcarrier_overlay.config(overlay=this.overlay)
    if this.curr_station_type == this.TYPE_STARPORT:
        this.starport_overlay.show_overlay()
    elif this.curr_station_type == this.TYPE_FLEETCARRIER:
        this.fleetcarrier_overlay.show_overlay()

def hide_overlay():
    if this.curr_station_type == this.TYPE_STARPORT:
        this.starport_overlay.hide_overlay()
    elif this.curr_station_type == this.TYPE_FLEETCARRIER:
        this.fleetcarrier_overlay.hide_overlay()

def show_station(show):
    if this.curr_show != show:
        this.curr_show = show
        if show:
            show_canvas()
            show_overlay()
        else:
            hide_canvas()
            hide_overlay()

def get_overlay_prefs(parent):

    this.use_overlay = config.get_bool(PREFSNAME_USE_OVERLAY, default=False)
    if config.get_str(PREFSNAME_MS_DELAY) is not None:
        this.over_ms_delay = int(config.get_str(PREFSNAME_MS_DELAY))

    split_me = config.get_str(PREFSNAME_STN_OVERLAY)
    if split_me:
        vals = split_me.split(":")
        this.over_center_x = int(vals[0])
        this.over_center_y = int(vals[1])
        this.over_radius = int(vals[2])

    split_me = config.get_str(PREFSNAME_COL_OVERLAY)
    if split_me:
        vals = split_me.split(":")
        this.over_color_stn = vals[0]
        this.over_color_pad = vals[1]

    split_me = config.get_str(PREFSNAME_SCR_OVERLAY)
    if split_me:
        vals = split_me.split("x")
        sw = float(vals[0])
        sh = float(vals[1])
    else:
        sw = float(parent.winfo_screenwidth())
        sh = float(parent.winfo_screenheight())

    this.starport_overlay = StarportPadsOverlay(
        this.overlay, this.backward, this.over_radius, this.over_center_x, this.over_center_y,
        sw, sh, this.over_ms_delay, this.over_color_stn, this.over_color_pad, this.over_ttl,
        None, this.starport_canvas,
    )
    this.fleetcarrier_overlay = FleetCarrierPadsOverlay(
        this.overlay, this.backward, this.over_radius, this.over_center_x, this.over_center_y,
        sw, sh, this.over_ms_delay, this.over_color_stn, this.over_color_pad, this.over_ttl,
        None, this.fleetcarrier_canvas,
    )

    this.prefs_radius = tk.IntVar(value=this.over_radius)
    this.prefs_center_x = tk.IntVar(value=this.over_center_x)
    this.prefs_center_y = tk.IntVar(value=this.over_center_y)
    this.prefs_screen_w = tk.IntVar(value=int(sw))
    this.prefs_screen_h = tk.IntVar(value=int(sh))
    this.prefs_use_over = tk.BooleanVar(value=this.use_overlay)
    this.prefs_ms_delay = tk.IntVar(value=this.over_ms_delay)

def try_overlay():
    # test for EDMC Overlay
    if this.use_overlay and this.overlay is None:
        try:
            this.overlay = Overlay(logger)
            this.overlay.connect()
        except:
            this.overlay = None
        if not this.overlay:
            logger.warning("EDMC Overlay not available")

def plugin_start3(plugin_dir):
    logger.info(f"{__version__ = }")
    return PLUGIN_NAME

def plugin_app(parent):
    # adapt to theme
    theme = config.get_int('theme')
    this.col_stn = config.get_str('dark_highlight') if theme else "black"
    this.col_pad = "yellow" if theme else "blue"

    # which side is green
    this.backward = config.get_bool(PREFSNAME_BACKWARD, default=False)
    this.greenside = tk.StringVar(value=OPTIONS_GREENSIDE[1 if this.backward else 0])

    # maximum plugin width for EDMC window
    this.max_width = config.get_int(PREFSNAME_MAX_WIDTH)
    if this.max_width != 0:
        this.max_width = max(this.max_width, MAX_WIDTH_MINIMUM)
    this.prefs_max_width = tk.IntVar(value=this.max_width)

    frame = tk.Frame(parent)                    # outer frame
    this.starport_frame = tk.Frame(frame)          # starport frame
    this.fleetcarrier_frame = tk.Frame(frame)      # fleetcarrier frame
    this.dummy = tk.Frame(frame)                   # dummy frame for resize/hide

    # station canvas
    this.use_canvas = not config.get_bool(PREFSNAME_HIDE_CANVAS, default=False)
    this.prefs_hide_canvas = tk.BooleanVar(value=not this.use_canvas)
    this.starport_canvas = StarportPads(
        this.starport_frame, highlightthickness=0, backward=this.backward,
        col_stn=this.col_stn, col_pad=this.col_pad, max_with=this.max_width,
    )
    this.starport_canvas.grid()
    this.fleetcarrier_canvas = FleetCarrierPads(
        this.fleetcarrier_frame, highlightthickness=0, backward=this.backward,
        col_stn=this.col_stn, col_pad=this.col_pad, max_with=this.max_width,
    )
    this.fleetcarrier_canvas.grid()

    # keep the station size in sync
    frame.bind("<Configure>", frame_resize)

    try_overlay()
    get_overlay_prefs(parent)

    # don't show the station
    show_station(False)

    logger.debug(f"{this = !s}")

    return frame

def plugin_prefs(parent, cmdr, is_beta):
    # EDMC defaults
    PADX, PADY = 5, 2

    frame = nb.Frame(parent)
    frame.columnconfigure(2, weight=1)

    HyperlinkLabel(
        frame, text=PLUGIN_NAME,
        background=nb.Label().cget('background'),
        url=PLUGIN_URL, underline=True
    ).grid(row=1, columnspan=2, padx=2*PADX, sticky=tk.W)
    nb.Label(frame, text=f'Version {__version__}').grid(row=1, column=2, padx=PADX, sticky=tk.E)

    nb.Label(frame, text='Greenside').grid(row=10, padx=2*PADX, pady=(PADX, 0), sticky=tk.W)
    nb.OptionMenu(frame, this.greenside, this.greenside.get(), *OPTIONS_GREENSIDE).grid(row=10, column=1, columnspan=2, padx=PADX, sticky=tk.W)

    nb.Label(frame, text='max. Width').grid(row=11, padx=2*PADX, pady=(PADX, 0), sticky=tk.W)
    nb.EntryMenu(frame, textvariable=this.prefs_max_width).grid(row=11, column=1, columnspan=2, padx=PADX, pady=PADY, sticky=tk.W)

    nb.Checkbutton(frame, text='Hide station canvas', variable=this.prefs_hide_canvas).grid(row=12, column=1, columnspan=2, padx=PADX, pady=PADY, sticky=tk.W)

    nb.Label(frame).grid(sticky=tk.W)
    nb.Label(frame, text='Overlay').grid(row=15, padx=2*PADX, pady=(PADX, 0), sticky=tk.W)
    nb.Checkbutton(frame, text='Use overlay if available', variable=this.prefs_use_over).grid(row=15, column=2, padx=PADX, sticky=tk.W)
    ttk.Separator(frame, orient=tk.HORIZONTAL).grid(columnspan=3, padx=PADX, pady=PADY, sticky=tk.EW)

    nb.Label(frame, text='Station').grid(row=20, padx=2*PADX, sticky=tk.W)
    nb.Label(frame, text='Radius').grid(row=20, column=1, padx=PADX, sticky=tk.E)
    nb.EntryMenu(frame, textvariable=this.prefs_radius).grid(row=20, column=2, padx=PADX, pady=PADY, sticky=tk.EW)

    nb.Label(frame, text='Center coordinates').grid(row=21, padx=2*PADX, sticky=tk.W)
    nb.Label(frame, text='X').grid(row=21, column=1, padx=PADX, sticky=tk.E)
    nb.EntryMenu(frame, textvariable=this.prefs_center_x).grid(row=21, column=2, padx=PADX, pady=PADY, sticky=tk.EW)
    nb.Label(frame, text='Y').grid(row=22, column=1, padx=PADX, sticky=tk.E)
    nb.EntryMenu(frame, textvariable=this.prefs_center_y).grid(row=22, column=2, padx=PADX, pady=PADY, sticky=tk.EW)

    nb.Label(frame, text='Screen').grid(row=23, padx=2*PADX, sticky=tk.W)
    nb.Label(frame, text='Width').grid(row=23, column=1, padx=PADX, sticky=tk.E)
    nb.EntryMenu(frame, textvariable=this.prefs_screen_w).grid(row=23, column=2, padx=PADX, pady=PADY, sticky=tk.EW)
    nb.Label(frame, text='Height').grid(row=24, column=1, padx=PADX, sticky=tk.E)
    nb.EntryMenu(frame, textvariable=this.prefs_screen_h).grid(row=24, column=2, padx=PADX, pady=PADY, sticky=tk.EW)

    nb.Label(frame, text='Drawing delay').grid(row=31, padx=2*PADX, sticky=tk.W)
    nb.Label(frame, text='msec').grid(row=31, column=1, padx=PADX, sticky=tk.E)
    nb.EntryMenu(frame, textvariable=this.prefs_ms_delay).grid(row=31, column=2, padx=PADX, pady=PADY, sticky=tk.EW)

    return frame

def prefs_changed(cmdr, is_beta):
    # adapt to theme
    theme = config.get_int('theme')
    this.col_stn = config.get_str('dark_highlight') if theme else "black"
    this.col_pad = "yellow" if theme else "blue"

    if this.greenside.get() == OPTIONS_GREENSIDE[1]:
        this.backward = True
    else:
        this.backward = False
    config.set(PREFSNAME_BACKWARD, this.backward)

    this.max_width = this.prefs_max_width.get()
    if this.max_width != 0:
        if this.max_width < 0:
            this.max_width = this.dummy.master.winfo_width()
        else:
            this.max_width = max(this.max_width, MAX_WIDTH_MINIMUM)
        this.prefs_max_width.set(this.max_width)
    this.starport_canvas.config(max_width=this.max_width)
    this.fleetcarrier_canvas.config(max_width=this.max_width)
    config.set(PREFSNAME_MAX_WIDTH, this.max_width)

    this.use_canvas = not this.prefs_hide_canvas.get()
    config.set(PREFSNAME_HIDE_CANVAS, not this.use_canvas)

    this.use_overlay = this.prefs_use_over.get()
    config.set(PREFSNAME_USE_OVERLAY, this.use_overlay)

    this.over_radius = this.prefs_radius.get()
    this.over_center_x = this.prefs_center_x.get()
    this.over_center_y = this.prefs_center_y.get()
    stn_prefs = "%d:%d:%d" % (this.over_center_x, this.over_center_y, this.over_radius)
    config.set(PREFSNAME_STN_OVERLAY, stn_prefs)

    sw = this.prefs_screen_w.get()
    sh = this.prefs_screen_h.get()
    scr_prefs = "%dx%d" % (sw, sh)
    config.set(PREFSNAME_SCR_OVERLAY, scr_prefs)

    this.over_ms_delay = this.prefs_ms_delay.get()
    config.set(PREFSNAME_MS_DELAY, str(this.over_ms_delay))

    # update station
    width = this.dummy.master.winfo_width()
    this.starport_canvas.config(col_stn=this.col_stn, col_pad=this.col_pad, backward=this.backward, width=width)
    this.fleetcarrier_canvas.config(col_stn=this.col_stn, col_pad=this.col_pad, backward=this.backward, width=width)
    if not this.use_overlay:
        this.overlay = None
        this.starport_overlay.hide_overlay()
        this.fleetcarrier_overlay.hide_overlay()
    this.starport_overlay.config(
        overlay=this.overlay, backward=this.backward, radius=this.over_radius,
        center_x=this.over_center_x, center_y=this.over_center_y,
        screen_w=float(sw), screen_h=float(sh), ms_delay=this.over_ms_delay,
    )
    this.fleetcarrier_overlay.config(
        overlay=this.overlay, backward=this.backward, radius=this.over_radius,
        center_x=this.over_center_x, center_y=this.over_center_y,
        screen_w=float(sw), screen_h=float(sh), ms_delay=this.over_ms_delay,
    )

def journal_entry(cmdr, is_beta, system, station, entry, state):
    if entry['event'] == 'DockingGranted':
        typ = entry.get('StationType', 'Unknown').lower()
        pad = int(entry['LandingPad'])
        if typ in this.starport_types:
            this.curr_station_type = this.TYPE_STARPORT
            this.starport_canvas.config(cur_pad=pad)
            this.starport_overlay.config(cur_pad=pad)
            show_station(True)
        elif typ in this.fleetcarrier_types:
            this.curr_station_type = this.TYPE_FLEETCARRIER
            is_squadroncarrier = len(entry["StationName"]) == 4
            this.fleetcarrier_canvas.config(cur_pad=pad, squadron_carrier=is_squadroncarrier)
            this.fleetcarrier_overlay.config(cur_pad=pad, squadron_carrier=is_squadroncarrier)
            show_station(True)
        else:
            this.curr_station_type = None
            logger.info(f"unsupported stationtype: {typ}")
    elif entry['event'] in this.hide_events:
        show_station(False)
        this.curr_station_type = None
    elif entry['event'] == 'Music':
        if entry['MusicTrack'] == "MainMenu":
            # only way I know, if the user logged out
            show_station(False)
            this.curr_station_type = None
    elif entry["event"] == "SendText":
        if entry["Message"].startswith("!pad"):
            if this.curr_station_type != this.TYPE_STARPORT:
                show_station(False)
            this.curr_station_type = this.TYPE_STARPORT
            try:
                pad = int(entry["Message"][4:])
            except ValueError:
                pad = None
            if pad:
                this.starport_canvas.config(cur_pad=pad)
                this.starport_overlay.config(cur_pad=pad)
                show_station(True)
            else:
                show_station(False)
        elif entry["Message"].startswith(("!fcpad", "!scpad")):
            if this.curr_station_type != this.TYPE_FLEETCARRIER:
                show_station(False)
            this.curr_station_type = this.TYPE_FLEETCARRIER
            try:
                pad = int(entry["Message"][6:])
            except ValueError:
                pad = None
            if pad:
                is_squadroncarrier = entry["Message"].startswith("!scpad")
                this.fleetcarrier_canvas.config(cur_pad=pad, squadron_carrier=is_squadroncarrier)
                this.fleetcarrier_overlay.config(cur_pad=pad, squadron_carrier=is_squadroncarrier)
                show_station(True)
            else:
                show_station(False)

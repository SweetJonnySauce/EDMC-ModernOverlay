import tkinter as tk

class LandingPads(tk.Canvas):

    def __init__(
        self, parent, cur_pad=None, backward=False,
        col_stn="black", col_pad="blue", max_with=0, **kwargs
    ):
        tk.Canvas.__init__(self, parent, **kwargs)
        self.bind("<Configure>", self.on_resize)
        self.width = self.winfo_reqwidth()
        self.max_width = max_with
        if self.max_width:
            self.width = min(self.width, self.max_width)
        self.height = self.width
        self.cur_pad = cur_pad
        self.col_pad = col_pad
        self.col_stn = col_stn
        self.pad_obj = None
        self.stn_obj = False
        self.backward = backward
        self.calc_values()

    def config(self, **kwargs):
        self.col_stn = kwargs.pop("col_stn", self.col_stn)
        self.col_pad = kwargs.pop("col_pad", self.col_pad)
        self.cur_pad = kwargs.pop("cur_pad", self.cur_pad)
        self.backward = kwargs.pop("backward", self.backward)
        self.max_width = kwargs.pop("max_width", self.max_width)
        if self.max_width and "width" in kwargs:
            kwargs["width"] = min(kwargs["width"], self.max_width)
            kwargs["height"] = kwargs["width"]
        tk.Canvas.config(self, **kwargs)
        self.draw_station()
        self.draw_pad(self.cur_pad)

    def on_resize(self, event):
        # resize the canvas
        self.width = self.height = event.width
        self.config(width=self.width, height=self.height)

    def calc_values(self):
        raise NotImplementedError

    def draw_station(self):
        raise NotImplementedError

    def draw_pad(self, pad):
        raise NotImplementedError

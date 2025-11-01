"""
    Miscellaneous support functions
"""

from .overlay import VIRTUAL_WIDTH, VIRTUAL_HEIGHT, VIRTUAL_ORIGIN_X, VIRTUAL_ORIGIN_Y


def round_away(val):
    """Round away from zero"""
    val += -0.5 if val < 0 else 0.5
    return int(val)

def calc_aspect_x(sw, sh):
    return (VIRTUAL_WIDTH+32) / (VIRTUAL_HEIGHT+18) * (sh-2*VIRTUAL_ORIGIN_Y) / (sw-2*VIRTUAL_ORIGIN_X)

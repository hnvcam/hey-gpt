#!/usr/bin/env python3
"""Accessible monochrome status glyphs. Run with system Python/python3-cairo.

Shapes, not color, carry state. Save both vector source and panel-friendly PNG.
"""
import math
from pathlib import Path
import cairo

ROOT=Path(__file__).resolve().parents[1]
STATES=('off','listening','hearing','dictating','waiting','typing','voice','error')
DARK=(.07,.09,.12)


def path(ctx,points,close=False):
    ctx.move_to(*points[0])
    for point in points[1:]:ctx.line_to(*point)
    if close:ctx.close_path()


def draw(ctx,name):
    ctx.set_source_rgb(*DARK)
    ctx.arc(32,32,29,0,2*math.pi);ctx.fill_preserve()
    ctx.set_source_rgb(1,1,1);ctx.set_line_width(2);ctx.stroke()
    ctx.set_line_width(5);ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    if name=='listening':
        ctx.arc(32,19,7,math.pi,2*math.pi);ctx.arc(32,31,7,0,math.pi);ctx.close_path();ctx.fill()
        ctx.move_to(19,29);ctx.line_to(19,32);ctx.arc_negative(32,32,13,math.pi,0);ctx.line_to(45,29);ctx.stroke()
        path(ctx,[(32,45),(32,53)]);path(ctx,[(25,53),(39,53)]);ctx.stroke()
    elif name=='hearing':
        for x,height in ((14,12),(23,28),(32,42),(41,28),(50,12)):
            path(ctx,[(x,32-height/2),(x,32+height/2)])
        ctx.stroke()
    elif name=='dictating':
        path(ctx,[(17,48),(21,34),(41,14),(51,24),(31,44)],True);ctx.fill()
        ctx.set_source_rgb(*DARK);ctx.set_line_width(3)
        path(ctx,[(37,18),(47,28)]);path(ctx,[(20,38),(27,45)]);ctx.stroke()
        ctx.set_source_rgb(1,1,1);ctx.set_line_width(4)
        path(ctx,[(16,53),(48,53)]);ctx.stroke()
    elif name=='waiting':
        path(ctx,[(18,12),(46,12),(46,20),(24,44),(24,51),(45,51)])
        path(ctx,[(18,51),(46,51),(46,44),(24,20),(24,12)])
        ctx.stroke()
    elif name=='typing':
        ctx.rectangle(11,20,42,28);ctx.stroke()
        for y in (27,34):
            for x in (18,27,36,45):ctx.rectangle(x-2,y-2,4,4)
        ctx.fill();ctx.set_line_width(3)
        path(ctx,[(23,41),(41,41)]);ctx.stroke()
    elif name=='voice':
        path(ctx,[(12,13),(43,13),(43,33),(24,33),(14,41),(14,33),(12,33)],True);ctx.stroke()
        path(ctx,[(48,25),(53,25),(53,45),(51,45),(51,52),(42,45),(30,45),(30,40)])
        ctx.stroke()
    elif name=='error':
        path(ctx,[(32,10),(55,51),(9,51)],True);ctx.fill()
        ctx.set_source_rgb(*DARK);ctx.set_line_width(5)
        path(ctx,[(32,24),(32,35)]);ctx.stroke()
        ctx.arc(32,44,3,0,2*math.pi);ctx.fill()
    elif name=='off':
        ctx.arc(32,34,19,-math.pi/3,4*math.pi/3);ctx.stroke()
        path(ctx,[(32,10),(32,32)]);ctx.stroke()


def render(name):
    surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,64,64)
    draw(cairo.Context(surface),name)
    surface.write_to_png(str(ROOT/'icons'/f'{name}.png'))
    with cairo.SVGSurface(str(ROOT/'icons'/f'{name}.svg'),64,64) as vector:
        draw(cairo.Context(vector),name)


if __name__=='__main__':
    for name in STATES:render(name)

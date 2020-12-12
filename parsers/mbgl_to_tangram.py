"""Mapbox GL JSON to Tangram Converter"""
import re
import requests

from typing import Union

from parsers.base import JSONStyleParser

text_field_regex = re.compile(r"{([^}]+)}")


layer_type_mappings = {
    "fill": "polygons",
    "line": "lines",
    "symbol": "symbol",
    "circle": "points",
    "fill-extrusion": "polygons",
}
boolean_mappings = {
    "any": "any",
    "all": "all",
}
binary_bool_ops = {
    "==",
    "!=",
    ">",
    ">=",
    "<",
    "<=",
}
geom_mappings = {
    "Point": "point",
    "MultiPoint": "point",
    "LineString": "line",
    "MultiLineString": "line",
    "Polygon": "polygon",
    "MultiPolygon": "polygon",
}
passthrough_tags = {
    "line-cap",
    "line-join",
    "symbol-placement",
    "symbol-spacing",
    "text-field",
    "text-font",
    "text-size",
    "text-transform",
    "visibility",
}


def convert_stops_or_value(expr, unit=""):
    scale = 2 if unit == "px" else None

    if isinstance(expr, list):
        return [[zoom, f"{float(value) / scale if scale else value}{unit}"] for (zoom, value) in expr]
    else:
        return f"{float(expr) / scale if scale else expr}{unit}"


class MBGLToTangramParser(JSONStyleParser):
    def render_layer_filter(self, expr, ctx=None):
        if isinstance(expr[0], str) and expr[0] in binary_bool_ops:
            return self.render_layer_filter(expr[1:], expr[0])
        elif isinstance(expr[0], str) and expr[0] in boolean_mappings:
            return {boolean_mappings[expr[0]]: self.render_layer_filter(expr[1:], boolean_mappings[expr[0]])}
        elif isinstance(expr[0], str):
            if expr[0] == "$type":
                return {"$geometry": geom_mappings[expr[1]]}
            elif expr[0] == "in":
                return {expr[1]: expr[2:]}
            elif expr[0] == "!in":
                return {"not": {expr[1]: expr[2:]}}
            elif ctx == "==":
                return {expr[0]: expr[1]}
            elif ctx == "!=":
                return {"not": {expr[0]: expr[1]}}
            elif ctx == ">":
                return {expr[0]: {"min": expr[1] + 1}}
            elif ctx == ">=":
                return {expr[0]: {"min": expr[1]}}
            elif ctx == "<":
                return {expr[0]: {"max": expr[1]}}
            elif ctx == "<=":
                return {expr[0]: {"max": expr[1] + 1}}
        elif ctx in {"any", "all"}:
            return [self.render_layer_filter(e) for e in expr]

        self.emit_warning(f"Unable to parse filter expr: {expr}\n")

    def render_text_source(self, expr: str):
        fmt = text_field_regex.fullmatch(expr)
        if fmt:
            # Single field
            return fmt.group(1)
        else:
            self.emit_warning(f"Unable to parse complex text source: {repr(expr)}")
        #     params = {}
        #
        #     def repl(match):
        #         cleaned = match.group(1).replace(':', '-')
        #
        #         params[cleaned] = match.group(1)
        #
        #         return match.group(1)
        #
        #     expr_cleaned = text_field_regex.sub(repl, expr)
        #     return expr_cleaned.format(**params)

    def render_draw(self, layer: dict):
        primary_type = layer["type"]
        if primary_type == "symbol":
            if layer.get("text-field"):
                primary_type = "text"
            else:
                primary_type = "points"

        order = layer["idx"]
        result = {
            primary_type: {},
        }
        primary_draw = result[primary_type]

        color = layer.get("color")
        if color:
            if primary_type == "text":
                primary_draw["font"] = {"fill": color}
            else:
                primary_draw["color"] = color

        if layer.get("width"):
            primary_draw["width"] = layer["width"]
        elif layer.get("type") == "lines":
            primary_draw["width"] = "0.5px"

        if layer.get("dash"):
            primary_draw["dash"] = layer["dash"]

        if not primary_draw:
            # At this point, we should have *something*
            # or the expression is invalid.
            self.emit_warning(f"Unable to render draw definition for layer {layer}")
            return None

        if primary_type == "text":
            primary_draw["move_into_tile"] = False
            primary_draw["style"] = "overlay_text"
            primary_draw["blend_order"] = order

            if layer.get("symbol-placement") == "line":
                primary_draw["placement"] = "spaced"
                primary_draw["placement_spacing"] = f"{layer.get('symbol-spacing', 2)}px"
            else:
                primary_draw["buffer"] = "2px"

            source = self.render_text_source(layer["text-field"])
            if source:
                primary_draw["text_source"] = source

            font = primary_draw.get("font", {})

            if layer.get("text-font"):
                family = layer["text-font"]
                if isinstance(family, list):
                    self.emit_warning("Multiple fonts specified, but only the first font will be preserved.")
                    family = family[0]

                font["family"] = family

            if layer.get("text-size"):
                font["size"] = layer["text-size"]

            if layer.get("text-transform"):
                font["transform"] = layer["text-transform"]

            font["priority"] = 999 - order

            primary_draw["font"] = font

            # TODO: Text halo?
            # TODO: Text blur?
            # TODO: Text translate?
        elif primary_type in {"polygons", "lines"}:
            primary_draw["order"] = order
            primary_draw["blend_order"] = order
            # TODO: Check if we need alpha
            primary_draw["style"] = f"inlay_{primary_type}"

            if layer.get("line-join"):
                primary_draw["join"] = layer["line-join"]

            if layer.get("line-cap"):
                primary_draw["cap"] = layer["line-cap"]

        return result

    def exiting_scope(self):
        if self.tag_path[0] == "layers" and len(self.tag_path) == 2:
            if self.ctx.get("layer"):
                ctx_layer = self.ctx.pop("layer")
                if ctx_layer.get("background"):
                    self.emit(("scene", "background", "color"), ctx_layer["background-color"])
                else:
                    layer = {}
                    layer_id = ctx_layer["id"]
                    source = ctx_layer.get("source")
                    source_layer = ctx_layer.get("source-layer")
                    zoom = {}

                    if source:
                        data = {"source": source}
                        if source_layer and source_layer != layer_id:
                            data["layer"] = source_layer

                        layer["data"] = data
                    else:
                        self.emit_warning(f"Layer has no source: {ctx_layer}")
                        return

                    draw = self.render_draw(ctx_layer)
                    if not draw:
                        return  # Errors reported internally

                    layer["draw"] = draw

                    if ctx_layer.get("minzoom"):
                        zoom["min"] = ctx_layer["minzoom"]
                    if ctx_layer.get("maxzoom"):
                        zoom["max"] = ctx_layer["maxzoom"]

                    if ctx_layer.get("filter"):
                        layer["filter"] = ctx_layer["filter"]

                    if zoom:
                        if not layer["filter"]:
                            layer["filter"] = {}

                        layer["filter"]["$zoom"] = zoom

                    self.emit(("layers", layer_id), layer)

    def visit_source(self, e: Union[str, int, float, list]):
        if self.tag_path[2] == "type":
            if e == "vector":
                self.emit(self.tag_path, "MVT")
                self.emit(self.tag_path[:-1] + ["tile_size"], 512)
            else:
                self.emit_warning(f"Unsupported source type: {e}")
        elif self.tag_path[2] == "url":
            res = requests.get(e)
            tilejson = res.json()
            tile_urls = tilejson["tiles"]
            if len(tile_urls) > 1:
                self.emit_warning("Only the first tile source URL has been imported")

            self.emit(self.tag_path, tile_urls[0])

            if tilejson.get("maxzoom"):
                self.emit(self.tag_path[:-1] + ["max_zoom"], tilejson["maxzoom"])
        elif self.tag_path[2] == "tiles":
            if len(e) > 1:
                self.emit_warning("Only the first tile source URL has been imported")

            self.emit(self.tag_path[:-1] + ["url"], e[0])
        elif self.tag_path[2] == "maxzoom":
            self.emit(self.tag_path[:-1] + ["max_zoom"], e)

    def visit_layer(self, e: Union[str, int, float, list]):
        if not self.ctx.get("layer"):
            self.ctx["layer"] = {"idx": self.tag_path[1]}

        layer = self.ctx["layer"]

        if self.tag_path[2] == "id":
            layer["id"] = e
        elif self.tag_path[2] == "type":
            if e == "background":
                # Special case
                layer["background"] = True
            else:
                layer["type"] = layer_type_mappings[e]
        elif self.tag_path[2] in {"source", "source-layer", "minzoom", "maxzoom"}:
            layer[self.tag_path[2]] = e
        elif self.tag_path[2] == "filter":
            layer["filter"] = self.render_layer_filter(e)
        elif self.tag_path[2] == "paint":
            if self.tag_path[3] == "background-color":
                # Background color
                layer["background-color"] = e
            elif self.tag_path[3] in {"fill-color", "line-color", "text-color"}:
                # TODO: This is probably a hackish assumption that one of these reduces to the layer "color"
                if len(self.tag_path) == 4 or self.tag_path[4] == "stops":
                    # TODO: Handle non-linear bases
                    layer["color"] = convert_stops_or_value(e)
            elif self.tag_path[3] == "line-dasharray":
                layer["dash"] = e
            elif self.tag_path[3] == "line-width":
                if len(self.tag_path) == 4 or self.tag_path[4] == "stops":
                    # TODO: Handle non-linear bases
                    layer["width"] = convert_stops_or_value(e, unit="px")
        elif self.tag_path[2] == "layout" and self.tag_path[3] in passthrough_tags:
            layer[self.tag_path[3]] = e

    def visit(self, e: Union[str, int, float, list]):
        # print(self.tag_path, e)
        if self.tag_path[0] == "layers":
            self.visit_layer(e)
        elif self.tag_path[0] == "sources":
            self.visit_source(e)

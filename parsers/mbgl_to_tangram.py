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
anchor_mappings = {
    # Mapbox swaps the order of what's anchored to what vs Tangram
    "center": "center",
    "left": "right",
    "right": "left",
    "top": "bottom",
    "bottom": "top",
    "top-left": "bottom-right",
    "bottom-right": "top-left",
    "top-right": "bottom-left",
    "bottom-left": "top-right",
}
passthrough_tags = {
    "icon-image",
    "icon-size",
    "line-cap",
    "line-join",
    "symbol-placement",
    "symbol-spacing",
    "text-anchor",
    "text-field",
    "text-font",
    "text-size",
    "text-transform",
    "visibility",
}


def convert_stops_or_value(expr, unit="", base=1.0, requires_meters_per_pixel=False):
    if isinstance(expr, list):
        if base == 1.0:
            return [[zoom, f"{value}{unit}"] for (zoom, value) in expr]
        else:
            # TODO: Handle colors and arrays of numbers(?)
            return f"""function() {{
    const zoom = $zoom;
    const stops = {expr};
    let lowerZoom = stops[0][0];
    let upperZoom = stops[1][0];
    let lowerValue = stops[0][1];
    let upperValue = stops[1][1];
    
    if (zoom < lowerZoom) return lowerValue;
    
    for (let i = 1; i < stops.length; i++) {{ 
        if (stops[i][0] > zoom) break;
        
        lowerZoom = upperZoom;
        upperZoom = stops[i][0];
        
        lowerValue = upperValue;
        upperValue = stops[i][1];
    }}
    
    const base = {base};
    const range = upperZoom - lowerZoom;
    const progress = zoom - lowerZoom;
    
    let ratio;
    
    if (range === 0) {{
        ratio = 0;
    }} else if (base === 1) {{
        ratio = progress / range;
    }} else {{
        ratio = (Math.pow(base, progress) - 1) / (Math.pow(base, range) - 1);
    }}
    
    const value = Math.min(upperValue, ((lowerValue * (1 - ratio)) + (upperValue * ratio)));
    return {"value * $meters_per_pixel" if requires_meters_per_pixel else "value"};
}}"""
    else:
        return f"{expr}{unit}"


def render_text_source(expr: str):
    fmt = text_field_regex.fullmatch(expr)
    if fmt:
        # Single field
        return fmt.group(1)
    else:

        def repl(match):
            return f"${{feature[\"{match.group(1)}\"] || ''}}"

        # NOTE: The trim is necessary in case the final field is blank/undefined.
        # Consider a multilingual map in which everything should be shown in Korean and
        # English. The Mapbox style may contain a format string like this: "{name:kr}\n{name:en}".
        # As most labels outside Korea will only be tagged in English, the resulting string may look
        # something like "\nErie". This will be rendered off-center by Tangram.
        return f"function() {{ return `{text_field_regex.sub(repl, expr)}`.trim() }}"


class MBGLToTangramParser(JSONStyleParser):
    def render_sprite(self, url):
        result = {
            "url": f"{url}@2x.png",
            "density": 2,
            "sprites": {},
        }

        res = requests.get(f"{url}@2x.json")

        for name, data in res.json().items():
            result["sprites"][name] = [data["x"], data["y"], data["width"], data["height"]]

        self.emit(("textures", "spritesheet"), result)

        self.emit(("styles", "icons"), {"base": "points", "blend": "overlay", "texture": "spritesheet"})

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

    def render_draw(self, layer: dict):
        order = layer["idx"]
        layer_type = layer["type"]

        text_draw = None
        icons_draw = None
        geom_draw = None
        result = {}

        if layer_type == "symbol":
            if layer.get("text-field"):
                text_draw = {}

                if layer.get("text-anchor"):
                    anchor = layer["text-anchor"]

                    if isinstance(anchor, str):
                        # Simple anchor
                        text_draw["anchor"] = anchor_mappings[anchor]
                    elif isinstance(anchor, dict) and isinstance(anchor.get("stops"), list):
                        # Stops... not really supported
                        value = anchor["stops"][0][1]
                        text_draw["anchor"] = anchor_mappings[value]
                        self.emit_warning(
                            f"Complex text anchor expressions are not supported. Picking the first stop {repr(value)} from {repr(anchor)}"
                        )
                    else:
                        self.emit_warning(f"Unable to parse text anchor expression: {repr(anchor)}")

                if layer.get("icon-image"):
                    icons_draw = {
                        "text": text_draw,
                        "priority": 999 - order,
                        "blend_order": 999,
                    }
                    result["icons"] = icons_draw
                else:
                    result["text"] = text_draw
            else:
                # TODO: Point only layers
                pass
        else:
            geom_draw = {}
            result[layer_type] = geom_draw

        # TODO: Figure out text and point ordering

        color = layer.get("color")
        if color:
            if text_draw is not None:
                text_draw["font"] = {"fill": color}
            else:
                geom_draw["color"] = color

        if layer.get("width") or layer.get("width-stops"):
            layer_width = layer.get("width", layer.get("width-stops"))
            base = layer.get("width-base", 1.0)

            layer_width = convert_stops_or_value(layer_width, unit="px", base=base, requires_meters_per_pixel=True)
            geom_draw["width"] = layer_width
        elif layer.get("type") == "lines":
            geom_draw["width"] = "1px"

        if layer.get("dash"):
            geom_draw["dash"] = layer["dash"]

        if not geom_draw and not text_draw:
            # At this point, we should have *something*
            # or the expression is invalid.
            self.emit_warning(f"Unable to render draw definition for layer {layer}")
            return None

        if text_draw:
            text_draw["blend_order"] = 999

            if not icons_draw:
                text_draw["priority"] = 999 - order

            if layer.get("symbol-placement") == "line":
                text_draw["placement"] = "spaced"

                spacing = layer.get("symbol-spacing")
                if spacing:
                    text_draw["placement_spacing"] = f"{spacing}px"

            source = render_text_source(layer["text-field"])
            if source:
                text_draw["text_source"] = source

            font = text_draw.get("font", {})

            if layer.get("text-font"):
                text_font = layer["text-font"]

                if isinstance(text_font, list):
                    # for family in text_font:
                    #     self.emit(("fonts", family), "external")

                    text_font = ", ".join(text_font)
                else:
                    pass
                    # self.emit(("fonts", text_font), "external")

                font["family"] = text_font

            if layer.get("text-size"):
                size = layer["text-size"]
                if isinstance(size, dict):
                    size = convert_stops_or_value(size["stops"], base=size.get("base", 1.0))

                font["size"] = size

            if layer.get("text-transform"):
                font["transform"] = layer["text-transform"]

            if layer.get("halo-color") and (layer.get("halo-width") or layer.get("halo-width-stops")):
                halo_width = layer.get("halo-width", layer.get("halo-width-stops"))
                # TODO: Base not supported
                if layer.get("halo-width-base", 1) != 1:
                    self.emit_warning("Unsupported exponential halo-width-base; this will be interpreted as linear.")

                halo_width = convert_stops_or_value(halo_width, unit="px")

                font["stroke"] = {
                    "color": layer["halo-color"],
                    "width": halo_width,
                }

            # Though dicts are mutable, if the font key did not previously exist, we still
            # need to set it here
            text_draw["font"] = font

            # TODO: Text blur?
            # TODO: Text translate?
        elif geom_draw:
            geom_draw["order"] = order
            geom_draw["blend_order"] = order
            # TODO: Check if we need alpha
            geom_draw["style"] = f"translucent_{layer_type}"

            if layer.get("line-join"):
                geom_draw["join"] = layer["line-join"]

            if layer.get("line-cap"):
                geom_draw["cap"] = layer["line-cap"]

        if icons_draw:
            icon = layer["icon-image"]
            if isinstance(icon, str):
                icons_draw["sprite"] = icon
            elif isinstance(icon, dict) and isinstance(icon.get("stops"), list):
                # Stops... not really supported
                value = icon["stops"][0][1]
                icons_draw["sprite"] = value
                self.emit_warning(
                    f"Complex icon-image expressions are not supported. Picking the first stop {repr(value)} from {repr(icon)}"
                )
            else:
                self.emit_warning(f"Unable to parse icon-image expression: {repr(icon)}")

            if layer.get("icon-size"):
                icons_draw["size"] = f"{layer['icon-size'] * 100}%"

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
            elif self.tag_path[3] == "text-halo-color":
                if len(self.tag_path) == 4 or self.tag_path[4] == "stops":
                    # TODO: Handle non-linear bases
                    layer["halo-color"] = convert_stops_or_value(e)
            elif self.tag_path[3] == "text-halo-width":
                if len(self.tag_path) == 4:
                    layer["halo-width"] = e
                elif self.tag_path[4] == "stops":
                    layer["halo-width-stops"] = e
                elif self.tag_path[4] == "base":
                    layer["halo-width-base"] = e
            elif self.tag_path[3] == "line-dasharray":
                layer["dash"] = e
            elif self.tag_path[3] == "line-width":
                if len(self.tag_path) == 4:
                    layer["width"] = e
                elif self.tag_path[4] == "stops":
                    layer["width-stops"] = e
                elif self.tag_path[4] == "base":
                    layer["width-base"] = e
        elif self.tag_path[2] == "layout" and self.tag_path[3] in passthrough_tags:
            if len(self.tag_path) > 4:
                # Create nested structure if necessary
                last = None
                for key in self.tag_path[3:-1]:
                    if last is None:
                        layer[key] = layer.get(key, {})
                        last = layer[key]
                    else:
                        last[key] = last.get(key, {})
                        last = last[key]
                last[self.tag_path[-1]] = e
            else:
                layer[self.tag_path[-1]] = e

    def visit(self, e: Union[str, int, float, list]):
        # print(self.tag_path, e)
        if self.tag_path[0] == "layers":
            self.visit_layer(e)
        elif self.tag_path[0] == "sources":
            self.visit_source(e)
        elif self.tag_path[0] == "sprite":
            self.render_sprite(e)

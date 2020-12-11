# Cartogrify

Cartogrify is a utility that helps you transmogrify cartographic styles
between formats.

This has been developed and tested with Python 3.8, but should be compatible
with 3.7+. (It will likely run in 3.6, but some assumptions are made about
dictionary order that are not sound before Python 3.7.)

Enough already though, how do I run it? First, do the usual `pip install -r requirements.txt`.
Argparse will happily give you the usage  info with `-h` if you run the main script.
At the moment there is only one mode and one argument (the input file).
Errors/warnings go to stderr, and the new style output goes to stdout. Pretty simple.

```
$ python cartogrify.py -h  # Get the auto generated usage info
$ python cartogrify.py mbgl2tangram /path/to/mbgl_style.json  # Dumps everything to the console, including warnings
$ python cartogrify.py mbgl2tangram /path/to/mbgl_style.json > /path/to/scene.yaml  # Preserve the output in a yaml file
```

## Supported formats

At the moment, only Mapbox GL JS -> Tangram is supported.

## Current status

This is EXPERIMENTAL software, and the codebase is littered with TODOs. If you have
relevant expertise, pull requests are most welcome :)

Don't expect it to do a perfect translation of your style out of the box, but it should
get you most of the way there though, and hopefully point out common issues that you need to be
aware of, as no two rendering engines share the same feature set.

### What should work

* Vector map sources (either specified inline with URL format or loaded via TileJSON)
* Background layer with a solid color
* Basic decision expressions (all boolean operators, `all`, and `any`) in layer filters
* Min and max zoom filters
* Linear stops for colors and line widths
* Basic color fill for polygons, lines, and text
* Line cap and join
* Text transformations

### What kind of works

Transparency works a bit differently... MBGL lets you specify a layer alpha, but Tangram
only lets you have colors with alpha, so you may notice a few rendering differences.

Text effects like halo and blur will be lost. These do not appear to have a *direct*
equivalent in Tangram, but there may be other ways to get the same effect.
Text layout does not seem to be exactly correct in all cases.
And Mapbox text format strings with more than one field referenced
are ignored at the moment.

Tangram does not appear to support multiple fonts in a fallback "stack" like Mapbox GL JS
does. Additionally, you are currently on your own for specifying fonts. A forthcoming version
will probably allow you to specify a Google Fonts API Key to locate common fonts automatically.
In light of the above though, you may be better off just combining all your glyphs into a custom
super-font.

Most of the above errors should be reported at runtime. Error detection is not
perfect, but well under way.

### What definitely doesn't work

* Exponential stops for colors and line widths (base is completely ignored, so they will be linear)
* Icons are not yet supported, but are definitely possible so expect these soon
* Probably everything else not mentioned here ;)

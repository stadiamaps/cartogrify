import argparse
import sys
import yaml

from parsers.mbgl_to_tangram import MBGLToTangramParser

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Transmogrify a cartographic theme into another format.")
    parser.add_argument("mode", type=str, choices=("mbgl2tangram",), help="The mode of transformation")
    parser.add_argument("infile", metavar="infile", type=str, help="The input file name")

    args = parser.parse_args()

    with open(args.infile, "r") as fp:
        # Only one option for now, but add others here as there is interest...
        if args.mode == "mbgl2tangram":
            import json

            style = json.load(fp)
            parser = MBGLToTangramParser(style)
            parser.parse()

            print(yaml.dump(parser.result, indent=2))

        sys.stderr.write("\n".join(f"Warning at {path}: {warning}" for (path, warning) in parser.warnings) + "\n")
        sys.stderr.flush()

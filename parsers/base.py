"""Parser base classes"""
from typing import Union


class JSONStyleParser:
    """A simple tree-walking parser base class for JSON styles.

    Subclasses must implement the visit method.

    Once initialising the parser with a `dict`, call the `parse`
    method to actually walk the tree. Each `dict` (or `dict` in
    a `list` of `dict`s) will be traversed, and terminal nodes
    (`list`s that are not populated with `dict`s, and primitive
    values) will be visited by `visit`. Subclasess may then make
    decisions based on the internal parser state, such as `tag_path`
    and `ctx` (a scratch space for subclasses to use for keeping
    track of contextual state).

    After `parse()` is complete, the result will be stored in the `result`
    property, and any warnings will be stored in the `warnings` property
    (as a list of the form `[(tag path, warning string)]`).
    """

    def __init__(self, style: dict):
        self.style = style
        self.tag_path = []
        self.result = {}
        self.warnings = []
        self.ctx = {}  # Scratch space for subclasses to use

    def parse(self):
        """Parser entrypoint."""
        assert not self.result
        self.__traverse(self.style)

    def emit(self, tag_path, e):
        """Emit a JSON compatible primitive at a given tag path"""
        insertion_point = self.result
        for level in tag_path[:-1]:
            if not insertion_point.get(level):
                insertion_point[level] = {}

            insertion_point = insertion_point[level]

        insertion_point[tag_path[-1]] = e

    def emit_warning(self, warning: str):
        self.warnings.append((self.tag_path.copy(), warning))

    def __traverse(self, e):
        for k, v in e.items():
            self.tag_path.append(k)
            if isinstance(v, dict):
                self.__traverse(v)
            elif isinstance(v, list) and all(isinstance(x, dict) for x in v):
                for (idx, x) in enumerate(v):
                    self.tag_path.append(idx)
                    self.__traverse(x)
                    self.exiting_scope()
                    self.tag_path.pop()
            else:
                self.visit(v)

            self.exiting_scope()
            self.tag_path.pop()

    def visit(self, e: Union[str, int, float, list]):
        raise NotImplementedError

    def exiting_scope(self):
        """Called immediately *before* an element is popped from the tag path.

        Subclasses may use this to detect when exiting a nested structure
        that needs to be treated as a complete unit.
        """
        raise NotImplementedError

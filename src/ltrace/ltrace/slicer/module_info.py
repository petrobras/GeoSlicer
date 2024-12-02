import ast
import os


class StopTraversal(Exception):
    pass


class CategoryVisitor(ast.NodeVisitor):
    def __init__(self, expectedClassName):
        self.categories = None
        self.hidden = False
        self.name = expectedClassName

    def visit_ClassDef(self, node):
        if node.name == self.name:
            if "LTracePlugin" in [base.id for base in node.bases]:
                self.generic_visit(node)  # Visit the children of the class

    def visit_Assign(self, node):
        # Check if the assignment is to `self.parent.categories`
        if isinstance(node.targets[0], ast.Attribute):
            attr = node.targets[0]
            if (
                isinstance(attr.value, ast.Attribute)
                and isinstance(attr.value.value, ast.Name)
                and attr.value.value.id == "self"
                and attr.value.attr == "parent"
            ):
                if attr.attr == "categories" and isinstance(node.value, ast.List):
                    # Extract the value (should be a list in this case)
                    self.categories = [elt.s for elt in node.value.elts]
                elif attr.attr == "hidden" and isinstance(node.value, ast.Constant):
                    # Extract the value (should be a boolean in this case)
                    self.hidden = node.value.value

                # Halt the traversal only when both categories and hidden are found
                if self.categories is not None and self.hidden is not False:
                    raise StopTraversal

        self.generic_visit(node)


# =============================================================================
#
# _ui_CreateComponentDialog
#
# =============================================================================
# =============================================================================
#
# ModuleInfo
#
# =============================================================================
class ModuleInfo:
    # ---------------------------------------------------------------------------
    def __init__(self, path, key=None, categories=None, hidden=False):
        self.path = path
        self.searchPath = os.path.dirname(path)
        self.categories = categories or []
        self.hidden = hidden

        if key is None:
            self.key = os.path.splitext(os.path.basename(path))[0]
        else:
            self.key = key

    # ---------------------------------------------------------------------------
    def __repr__(self):
        return "ModuleInfo(key=%(key)r, path=%(path)r, hidden=%(hidden)r" % self.__dict__

    # ---------------------------------------------------------------------------
    def __str__(self):
        return self.path

    # ---------------------------------------------------------------------------
    @staticmethod
    def findModules(path, depth):
        result = []
        if os.path.isfile(path):
            entries = [path]
        elif os.path.isdir(path):
            entries = [os.path.join(path, entry) for entry in os.listdir(path)]
            # If the folder contains __init__.py, it means that this folder
            # is not a Slicer module but an embedded Python library that a module will load.
            if any(entry.endswith("__init__.py") for entry in entries):
                entries = []
        else:
            # not a file or folder
            return result

        if depth > 0:
            for entry in filter(os.path.isdir, entries):
                result += ModuleInfo.findModules(entry, depth - 1)

        for entry in filter(os.path.isfile, entries):
            if not entry.endswith(".py"):
                continue

            if os.path.basename(entry) == "__init__.py":
                continue

            # Criteria for a Slicer module to have a module class
            # that has the same name as the filename and its base class is LTracePlugin.

            if entry.endswith("CLI.py") and os.path.dirname(entry).endswith("CLI"):
                # Dirty but works / TODO move it to a function specialized for CLI
                result.append(ModuleInfo(entry, categories=["CLI"], hidden=False))
                continue

            try:
                # Find all class definitions
                with open(entry) as entry_file:
                    tree = ast.parse(entry_file.read())

                filename = os.path.basename(entry)
                expectedClassName = os.path.splitext(filename)[0]
                visitor = CategoryVisitor(expectedClassName)
                try:
                    visitor.visit(tree)
                except StopTraversal:
                    pass

                if visitor.categories:
                    minfo = ModuleInfo(entry, categories=visitor.categories, hidden=visitor.hidden)
                    result.append(minfo)

            except:
                # Error while processing the file (e.g., syntax error),
                # it cannot be a Slicer module.
                pass

            # We have the option to identify scripted CLI modules, such as by examining the existence of a
            # compatible module descriptor XML file. However, this type of module is relatively uncommon, so
            # the decision was made not to invest in implementing this feature.

        return result

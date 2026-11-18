import ast
import warnings
import os
import logging
import traceback


class StopTraversal(Exception):
    pass


class CategoryVisitor(ast.NodeVisitor):
    def __init__(self, expectedClassName):
        self.categories = None
        self.hidden = False
        self.name = expectedClassName
        self.classFound = False
        self.derivesFromPlugin = False

    def visit_ClassDef(self, node):
        if node.name == self.name:
            self.classFound = True
            if "LTracePlugin" in [getattr(base, "id", "") for base in node.bases]:
                self.derivesFromPlugin = True
                self.generic_visit(node)  # Visit the children of the class

    def problem(self):
        """Why the file is not a module, or None if it is one."""
        if not self.classFound:
            return (
                f"No class named '{self.name}' was found. A module must define a class with the same name as its file."
            )
        if not self.derivesFromPlugin:
            return f"Class '{self.name}' must derive from LTracePlugin."
        if not self.categories:
            return f"Class '{self.name}' must set self.parent.categories to a list of categories."
        return None

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
                    self.categories = [elt.value for elt in node.value.elts]
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
    def findModules(path, depth, problems=None):
        """Find the modules under path. If a problems list is given, files that should be modules but aren't (a
        file named after its folder, like Foo/Foo.py) are appended to it as (ModuleInfo, message, details)."""
        result = []
        if os.path.isfile(path):
            entries = [path]
        elif os.path.isdir(path):
            entries = [os.path.join(path, entry) for entry in sorted(os.listdir(path))]
            # If the folder contains __init__.py, it means that this folder
            # is not a Slicer module but an embedded Python library that a module will load.
            if any(entry.endswith("__init__.py") for entry in entries):
                entries = []
        else:
            # not a file or folder
            return result

        if depth > 0:
            for entry in filter(os.path.isdir, entries):
                result += ModuleInfo.findModules(entry, depth - 1, problems)

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

            filename = os.path.basename(entry)
            expectedClassName = os.path.splitext(filename)[0]
            isModuleFile = problems is not None and expectedClassName == os.path.basename(os.path.dirname(entry))

            try:
                # Find all class definitions
                with open(entry, encoding="utf-8") as entry_file:
                    source_code = entry_file.read()

                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", SyntaxWarning)
                    tree = ast.parse(source_code, entry)

                visitor = CategoryVisitor(expectedClassName)
                try:
                    visitor.visit(tree)
                except StopTraversal:
                    logging.info(
                        f"Found module class {expectedClassName} in {entry} with categories {visitor.categories} and hidden={visitor.hidden}"
                    )

                if visitor.categories:
                    minfo = ModuleInfo(entry, categories=visitor.categories, hidden=visitor.hidden)
                    result.append(minfo)
                elif isModuleFile:
                    problems.append((ModuleInfo(entry), visitor.problem(), ""))

            except SyntaxError as error:
                logging.warning(f"Failed to parse {entry} as a Slicer module. It will be ignored.")
                if isModuleFile:
                    details = "".join(traceback.format_exception_only(error)).rstrip()
                    problems.append((ModuleInfo(entry), f"Syntax error on line {error.lineno}: {error.msg}", details))
            except Exception as error:
                logging.warning(f"Failed to parse {entry} as a Slicer module. It will be ignored.")
                if isModuleFile:
                    problems.append((ModuleInfo(entry), f"Could not read the file: {error}", ""))

            # We have the option to identify scripted CLI modules, such as by examining the existence of a
            # compatible module descriptor XML file. However, this type of module is relatively uncommon, so
            # the decision was made not to invest in implementing this feature.

        return result

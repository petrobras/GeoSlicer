import slicer, qt

from natsort import natsorted


# =============================================================================
#
# _ui_DirectoryListWidget
#
# =============================================================================
class _ui_DirectoryListWidget(object):
    # ---------------------------------------------------------------------------
    def __init__(self, parent):
        layout = qt.QGridLayout(parent)

        self.pathList = slicer.qSlicerDirectoryListView()
        layout.addWidget(self.pathList, 0, 0, 3, 1)

        self.addPathButton = qt.QToolButton()
        self.addPathButton.icon = qt.QIcon.fromTheme("list-add")
        self.addPathButton.text = "Add"
        layout.addWidget(self.addPathButton, 0, 1)

        self.removePathButton = qt.QToolButton()
        self.removePathButton.icon = qt.QIcon.fromTheme("list-remove")
        self.removePathButton.text = "Remove"
        layout.addWidget(self.removePathButton, 1, 1)


# =============================================================================
#
# DirectoryListWidget
#
# =============================================================================
class DirectoryListWidget(qt.QWidget):
    # ---------------------------------------------------------------------------
    def __init__(self, *args, **kwargs):
        qt.QWidget.__init__(self, *args, **kwargs)
        self.ui = _ui_DirectoryListWidget(self)

        self.ui.addPathButton.connect("clicked()", self.addDirectories)
        self.ui.removePathButton.connect("clicked()", self.ui.pathList, "removeSelectedDirectories()")

    # ---------------------------------------------------------------------------
    def addDirectory(self):
        path = qt.QFileDialog.getExistingDirectory(self.window(), "Select folder")
        if len(path):
            self.ui.pathList.addDirectory(path)

    def addDirectories(self):
        file_dialog = qt.QFileDialog()
        file_dialog.setFileMode(qt.QFileDialog.DirectoryOnly)
        file_view = file_dialog.findChild(qt.QListView, "listView")
        if file_view:
            file_view.setSelectionMode(qt.QAbstractItemView.ExtendedSelection)

        f_tree_view = file_dialog.findChild(qt.QTreeView)
        if f_tree_view:
            f_tree_view.setSelectionMode(qt.QAbstractItemView.ExtendedSelection)

        if file_dialog.exec():
            paths = file_dialog.selectedFiles()
            for path in natsorted(paths):
                if len(path):
                    self.ui.pathList.addDirectory(path)

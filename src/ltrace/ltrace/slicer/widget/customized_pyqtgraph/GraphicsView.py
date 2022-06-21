# Reimplemented from https://github.com/pyqtgraph/pyqtgraph
# commit cef0870
# fmt: off

import pyqtgraph as pg

class GraphicsView(pg.GraphicsView):
    def setCentralWidget(self, item):
        """Sets a QGraphicsWidget to automatically fill the entire view (the item will be automatically
        resize whenever the GraphicsView is resized)."""
        if self.centralWidget is not None:
            self.scene().removeItem(self.centralWidget)
        self.centralWidget = item
        if item is not None:
            self.sceneObj.addItem(item)

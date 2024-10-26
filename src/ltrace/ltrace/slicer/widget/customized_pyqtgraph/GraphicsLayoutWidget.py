# Downloaded from https://github.com/pyqtgraph/pyqtgraph
# commit cef0870
# fmt: off
from pyqtgraph.graphicsItems.GraphicsLayout import GraphicsLayout
from pyqtgraph.Qt import mkQApp
from ltrace.slicer.widget.customized_pyqtgraph.GraphicsView import GraphicsView

__all__ = ['GraphicsLayoutWidget']
class GraphicsLayoutWidget(GraphicsView):
    """
    Convenience class consisting of a :class:`GraphicsView 
    <pyqtgraph.GraphicsView>` with a single :class:`GraphicsLayout
    <pyqtgraph.GraphicsLayout>` as its central item. 

    This widget is an easy starting point for generating multi-panel figures.
    Example::
    
        w = pg.GraphicsLayoutWidget()
        p1 = w.addPlot(row=0, col=0)
        p2 = w.addPlot(row=0, col=1)
        v = w.addViewBox(row=1, col=0, colspan=2)
    
    =========  =================================================================
    parent     (QWidget or None) The parent widget.
    show       (bool) If True, then immediately show the widget after it is
               created. If the widget has no parent, then it will be shown
               inside a new window.
    size       (width, height) tuple. Optionally resize the widget. Note: if
               this widget is placed inside a layout, then this argument has no
               effect.
    title      (str or None) If specified, then set the window title for this
               widget.
    kargs      All extra arguments are passed to
               :meth:`GraphicsLayout.__init__
               <pyqtgraph.GraphicsLayout.__init__>`
    =========  =================================================================
        

    This class wraps several methods from its internal GraphicsLayout:
    :func:`nextRow <pyqtgraph.GraphicsLayout.nextRow>`
    :func:`nextColumn <pyqtgraph.GraphicsLayout.nextColumn>`
    :func:`addPlot <pyqtgraph.GraphicsLayout.addPlot>`
    :func:`addViewBox <pyqtgraph.GraphicsLayout.addViewBox>`
    :func:`addItem <pyqtgraph.GraphicsLayout.addItem>`
    :func:`getItem <pyqtgraph.GraphicsLayout.getItem>`
    :func:`addLabel <pyqtgraph.GraphicsLayout.addLabel>`
    :func:`addLayout <pyqtgraph.GraphicsLayout.addLayout>`
    :func:`removeItem <pyqtgraph.GraphicsLayout.removeItem>`
    :func:`itemIndex <pyqtgraph.GraphicsLayout.itemIndex>`
    :func:`clear <pyqtgraph.GraphicsLayout.clear>`
    """
    def __init__(self, parent=None, show=False, size=None, title=None, **kargs):
        mkQApp()
        GraphicsView.__init__(self, parent)
        self.ci = GraphicsLayout(**kargs)
        for n in ['nextRow', 'nextCol', 'nextColumn', 'addPlot', 'addViewBox', 'addItem', 'getItem', 'addLayout', 'addLabel', 'removeItem', 'itemIndex', 'clear']:
            setattr(self, n, getattr(self.ci, n))
        self.setCentralItem(self.ci)
        
        if size is not None:
            self.resize(*size)
            
        if title is not None:
            self.setWindowTitle(title)
            
        if show is True:
            self.show()

    def showEvent(self, event):
        super().showEvent(event)

        # Avoid being stuck at an increasing minimum width
        self.setMinimumWidth(10)
        maximum_width = self.maximumWidth()
        self.setMaximumWidth(10)
        self.setMaximumWidth(maximum_width)

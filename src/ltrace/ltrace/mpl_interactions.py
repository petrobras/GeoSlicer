import warnings

from matplotlib import __version__ as mpl_version


# functions that are methods
__all__ = ["zoom_factory", "panhandler"]

# based on https://gist.github.com/tacaswell/3144287
def zoom_factory(ax, base_scale=1.1):
    """
    Add ability to zoom with the scroll wheel.

    parameters
    ----------
    ax : matplotlib axes object
        axis on which to implement scroll to zoom
    base_scale : float
        how much zoom on each tick of scroll wheel

    returns
    -------
    disconnect_zoom : function
        call this to disconnect the scroll listener
    """

    def limits_to_range(lim):
        return lim[1] - lim[0]

    fig = ax.get_figure()  # get the figure of interest
    fig.canvas.capture_scroll = True
    has_toolbar = hasattr(fig.canvas, "toolbar") and fig.canvas.toolbar is not None
    if has_toolbar:
        # it might be possible to have an interactive backend without
        # a toolbar. I'm not sure so being safe here
        toolbar = fig.canvas.toolbar
        toolbar.push_current()
    orig_xlim = ax.get_xlim()
    orig_ylim = ax.get_ylim()
    orig_yrange = limits_to_range(orig_ylim)
    orig_xrange = limits_to_range(orig_xlim)
    orig_center = ((orig_xlim[0] + orig_xlim[1]) / 2, (orig_ylim[0] + orig_ylim[1]) / 2)

    def zoom_fun(event):
        # get the current x and y limits
        cur_xlim = ax.get_xlim()
        cur_ylim = ax.get_ylim()
        # set the range
        cur_xrange = (cur_xlim[1] - cur_xlim[0]) * 0.5
        cur_yrange = (cur_ylim[1] - cur_ylim[0]) * 0.5
        xdata = event.xdata  # get event x location
        ydata = event.ydata  # get event y location
        if event.button == "up":
            # deal with zoom in
            scale_factor = base_scale
        elif event.button == "down":
            # deal with zoom out
            scale_factor = 1 / base_scale
        else:
            # deal with something that should never happen
            scale_factor = 1
        # set new limits
        new_xlim = [
            xdata - (xdata - cur_xlim[0]) / scale_factor,
            xdata + (cur_xlim[1] - xdata) / scale_factor,
        ]
        new_ylim = [
            ydata - (ydata - cur_ylim[0]) / scale_factor,
            ydata + (cur_ylim[1] - ydata) / scale_factor,
        ]
        new_yrange = limits_to_range(new_ylim)
        new_xrange = limits_to_range(new_xlim)

        if abs(new_yrange) > abs(orig_yrange):
            new_ylim = orig_center[1] - new_yrange / 2, orig_center[1] + new_yrange / 2
        if abs(new_xrange) > abs(orig_xrange):
            new_xlim = orig_center[0] - new_xrange / 2, orig_center[0] + new_xrange / 2
        ax.set_xlim(new_xlim)
        ax.set_ylim(new_ylim)

        if has_toolbar:
            toolbar.push_current()
        ax.figure.canvas.draw_idle()  # force re-draw

    # attach the call back
    cid = fig.canvas.mpl_connect("scroll_event", zoom_fun)

    def disconnect_zoom():
        fig.canvas.mpl_disconnect(cid)

    # return the disconnect function
    return disconnect_zoom


class panhandler:
    """
    Enable panning a plot with any mouse button.

    button determines which button will be used (default right click)
    Left: 1
    Middle: 2
    Right: 3
    """

    def __init__(self, fig, button=3):
        self.fig = fig
        self._id_drag = None
        self.button = button
        self.fig.canvas.mpl_connect("button_press_event", self.press)
        self.fig.canvas.mpl_connect("button_release_event", self.release)

    def _cancel_action(self):
        self._xypress = []
        if self._id_drag:
            self.fig.canvas.mpl_disconnect(self._id_drag)
            self._id_drag = None

    def press(self, event):
        print("1 //", repr(event))
        if event.button != self.button:
            self._cancel_action()
            return

        print("2 //", repr(event))

        x, y = event.x, event.y

        self._xypress = []
        for i, a in enumerate(self.fig.get_axes()):
            if x is not None and y is not None and a.in_axes(event) and a.get_navigate() and a.can_pan():
                a.start_pan(x, y, event.button)
                self._xypress.append((a, i))
                self._id_drag = self.fig.canvas.mpl_connect("motion_notify_event", self._mouse_move)
                print("3 //", repr(event))

    def release(self, event):
        self._cancel_action()
        self.fig.canvas.mpl_disconnect(self._id_drag)

        for a, _ind in self._xypress:
            a.end_pan()
        if not self._xypress:
            self._cancel_action()
            return
        self._cancel_action()

    def _mouse_move(self, event):
        for a, _ind in self._xypress:
            # safer to use the recorded button at the _press than current
            # button: # multiple button can get pressed during motion...
            a.drag_pan(1, event.key, event.x, event.y)
        self.fig.canvas.draw_idle()

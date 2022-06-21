# Charts

Extension of _GeoSlicer_, developed by LTRACE, for data visualization through different types of graphs. Currently, it is possible to generate graphs only from data contained in Table.

__Available plots__

* Crossplot: 2D or 3D crossplot with attached histogram on each axis. The third dimension (z axis) is represented by a color scale.

* Rosette diagram: Rosette diagram to visualize the frequency of values (histogram) of the entered data in terms of angles. Check the box _Semi-circle_ to limit the visualization from 270 to 90 degrees (or -90 to 90 degrees); uncheck the box _Semi-circle_ to visualize the full circle 360 degrees.

* Transition: Data visualization as bar. The displayed data refers from the quantification of the table's rows's values, associated to the respective column.
__Module Interface__

1. __Data to plot__: Select the table with the data to be ploted. Each column is interpreted as a different property/variable to plot.
2. __Plot type__: Select type of plot, crossplot or rosette diagram. 
3. __Plot to__: Select a previously defined plot to visualize multiples data in a same window/graph. 

__Plot Interface__

1. On the top of the window, the user can see a list with all the tables loaded for graph visualization. The _eye_ icon is used to define each table should be visualize; the grey _square_ is used to change the color of the points; and the red _X_ is used to delete the table from the list.
2. On the graph, the user can move the scale by holding left-click + moving the cursor and ascess more visual options by right clicking on the graph. 
3. On the botton, the user selects the properties to be plotted as X, Y and Z axis.

function loadVTKFiles(urls) {
    let promise = Promise.resolve();
    const polyDatas = [];
    var reader;
    urls.forEach(url => {
        promise = promise.then(() => {
            const reader = url.endsWith(".vtp") 
                  ? vtk.IO.XML.vtkXMLPolyDataReader.newInstance() 
                  : vtk.IO.Legacy.vtkPolyDataReader.newInstance();
            
            return reader.setUrl("/app/static/".concat(url)).then(() => {
                return reader.loadData().then(() => {
                    const polyData = reader.getOutputData();
                    polyDatas.push(polyData);
                });
            });
        });
    });

    return promise.then(() => polyDatas);
}

function compareArrays(arr1, arr2) {
    if (arr1.length !== arr2.length) {
        return false;
    }
    for (let i = 0; i < arr1.length; i++) {
        if (arr1[i] !== arr2[i]) {
            return false;
        }
    }
    return true;
}

function onRender(event) {
    const container = document.querySelector('#viewport');
    const loading_animation = document.querySelector('#loading_animation');

    const { filenames, geometries_colors, bg_color, ui_collapsed, rotate, key } = event.detail.args;

    if (typeof old_args !== 'undefined' && !compareArrays(filenames, old_args)) {
        window.rendered = false;
    }
    
    if (!window.rendered) {
        const filenamesArray = Array.isArray(filenames) ? filenames : [filenames];
        const nrrdFiles = filenamesArray.filter(filename => filename.split('.').pop() === 'nrrd');
        const vtkFiles = filenamesArray.filter(filename => filename.split('.').pop() === 'vtk' || filename.split('.').pop() === 'vtp');

        loading_animation.style.display = 'block';
	container.style.display = 'none';

        if (nrrdFiles.length > 0) {
            const filename = nrrdFiles[0];
            const image = new URL(
                "/app/static/".concat(filename),
                window.location.origin,
            );
            
            itkVtkViewer.createViewer(container, {
                image
            }).then(viewer => {
                viewer.setBackgroundColor(bg_color);
                viewer.setUICollapsed(ui_collapsed);
                viewer.setRotateEnabled(rotate);
                viewer.setImageColorMap('X Ray', 0);
                viewer.setUnits('mm');
                viewer.setImageGradientOpacity(0.0);
                viewer.setImageVolumeSampleDistance(0.0);
                loading_animation.style.display = 'none';
		container.style.display = 'block';
            });
        }
        else if (vtkFiles.length > 0) {
            loadVTKFiles(vtkFiles).then(polyDatas => {
                itkVtkViewer.createViewer(container, {
                    geometries: polyDatas,
                }).then(viewer => {
                    viewer.setBackgroundColor(bg_color);
                    viewer.setUICollapsed(ui_collapsed);
                    viewer.setRotateEnabled(rotate);
                    viewer.setUnits('mm');
                    if (geometries_colors && geometries_colors.length === polyDatas.length) {
                        for (var i = 0; i < geometries_colors.length; i++) {
                            color = geometries_colors[i];
                            if (color) {
                                viewer.setGeometryColor(i, color.slice(0, 3));
                                if (color.length === 4) {
                                    viewer.setGeometryOpacity(i, color[3]);
                                }
                            }
                        }
                    }
                    loading_animation.style.display = 'none';
		    container.style.display = 'block';
                }).catch(error => {
                    console.error("Error loading VTK files:", error);
                    loading_animation.style.display = 'none';
		    container.style.display = 'none';
                });
            });
        }

        Streamlit.setFrameHeight(600);
        window.rendered = true;
        old_args = filenames;
    }
}

Streamlit.events.addEventListener(Streamlit.RENDER_EVENT, onRender);
Streamlit.setComponentReady();
Streamlit.setFrameHeight();

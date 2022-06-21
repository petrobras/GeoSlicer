# GeoSlicer Script Repository

Bunch of scripts/snippets that would be useful for development.

## External Repositories

[Slicer's Script Repository](https://www.slicer.org/wiki/Documentation/Nightly/ScriptRepository) (when adding a new script/snippet, first consider contributing to this source instead of ours)

[Transforms Scripts](https://www.slicer.org/wiki/Documentation/Nightly/Modules/Transforms#Examples)

## Developer mode

Some controls are only helpful for testing, so we hide them behind Slicer's `developer mode` toggle.
To check for it use  `ltrace.slicer_utils.slicer_is_in_developer_mode()`

## Settings

Slicer has 2 types of settings: one for the whole application and one only for the current version.
To get them use `slicer.app.userSettings()` and `revision_settings = slicer.app.revisionUserSettings()`.
* Note: The revision setting is only for the **Slicer** version and not **GeoSlicer**.

## Scripts/snippets

### Simple way to apply a hardened transformation to a node
```python
translationArray = np.identity(4)
translationArray[:3, 3] = coordinates
node.ApplyTransformMatrix(slicer.util.vtkMatrixFromArray(translationArray))
```
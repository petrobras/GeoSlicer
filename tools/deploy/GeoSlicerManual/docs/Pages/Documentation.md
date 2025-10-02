# Linking

## Page links

If **navigation is important**, link to the full path:

```
[Saturation](/Volumes/Microporosity/PorosityFromSaturation.md)
```

The absolute path is converted to a relative path during build.

After clicking, the following will be open in the navbar: *Volumes > Microporosity > Porosity From Saturation*

If **navigation is not important**, you can link directly:

```
[Saturation](PorosityFromSaturation.md)
```

This is equivalent to `./PorosityFromSaturation.md` and assumes all pages are in the same directory.

## Images

```
![alt text](/assets/images/foo.png)
```

The absolute path is also converted to a relative path during build.

## Videos

```
{{ video("video_name.webm", caption="Optional caption") }}
```

Videos are automatically sourced from `/assets/videos/`.
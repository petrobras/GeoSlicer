# Linking

## Page links

If **navigation is important**, link to the full path:

```
[Saturation](/Volumes/Microporosity/Microporosity.md)
```

The absolute path is converted to a relative path during build.

After clicking, the following will be open in the navbar: *Volumes > Microporosity*

If **navigation is not important**, you can link directly:

```
[Saturation](Microporosity.md)
```

This is equivalent to `./Microporosity.md` and assumes all pages are in the same directory.

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

## Anchor

For multiple languages compatibility, use the tag `<a>` in the desired header text, including the `id` definition in _english_.

This approach ensures that a link like `[some text](page.md#title-simulation)` will navigate to the correct section, regardless of whether the user is viewing the English or Portuguese page. It also prevents `mkdocs` from reporting broken links during the build process.

```
Header in Portuguese page:
<a id="title-simulation">Simulação de Título</a>

Header in English page:
<a id="title-simulation">Title Simulation</a>
```
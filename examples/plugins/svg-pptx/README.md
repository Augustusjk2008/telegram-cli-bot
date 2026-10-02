# SVG → PPTX

One static SVG becomes one PowerPoint slide with the same aspect ratio. Ordinary
`text` / `tspan` become editable text boxes; graphics become transparent PNG
layers in SVG drawing order. Office is not required to export.

Copy this entire directory into the Orbit plugin directory (normally
`~/.tcb/plugins/svg-pptx`), or install it through the existing plugin installer.
Refresh the plugin catalog, then open a workspace `.svg` file with **SVG 转 PPTX**.
The table shows canvas dimensions, text/layer counts, warnings and error reasons.
**导出 PPTX** downloads the generated slide. Unsupported input disables export.
Copy `samples/sample.svg` into your workspace to try bilingual text, inherited
CSS, multiline `tspan` and overlapping graphic layers.

Install dependencies using the **same Python interpreter that runs Orbit**.
The missing-dependency table displays the exact command, including the host
interpreter and installed plugin paths. For example, in Windows PowerShell:

```powershell
& "C:\path\to\host\python.exe" -m pip install -r "C:\path\to\plugins\svg-pptx\requirements.txt"
```

Replace both paths with the paths displayed by the plugin. It never installs
packages automatically. Missing dependencies leave the view available with an
installation hint and export disabled. Text uses local fonts; unavailable fonts
may be substituted with a warning. The receiving computer also needs suitable
fonts to preserve PowerPoint layout when editing.

Supported text includes Chinese/English, continuous styled runs, and independently
positioned `tspan` lines. SVG `width`, `height` and nonzero `viewBox` are normalized;
pixel and common physical units are accepted. Presentation attributes, inline
styles, ordinary internal CSS selectors and inheritance preserve font family,
size, bold/italic, solid color, opacity, text anchor and common baselines.
Nested translation, uniform scaling and rotation use SVG transform syntax.
Graphics can include paths, shapes, internal references and embedded raster images.
Text converted to paths or embedded in images remains graphics.

Unsupported input disables export and names the element and reason. This includes
`textPath`, flowed text, per-character positioning/rotation, `textLength`, text
strokes/gradients, clipping/masks/filters on text, skew, mirrors, nonuniform scaling,
nested text viewports, conditional text, group opacity affecting text, CSS canvas
dimensions, CSS variables and stylesheet at-rules. Use `x/y/dx/dy` attributes for
text positions. XML whitespace preservation is inherited. Fonts are not embedded;
the same installed face measures and writes each run. SVG and PowerPoint font
engines can produce small differences in glyph edges and baselines.

Source reads and artifact publication use the Host API. Only `workspaceRead`
and `tempArtifacts` permissions are requested. Export rereads the SVG; it never
uses a cached source. External XML entities, scripts, external files and network
resources are rejected. Internal references and embedded image data are accepted
within the converter's supported scope (PNG/JPEG/GIF/WebP, not embedded SVG).
Dependencies and fonts are local; this
plugin does not fetch source resources.

Inspect and export each run in an independent worker using the host Python.
The default timeout is 45 seconds (maximum 55); timeout kills and reaps only that
conversion worker. Defaults are a 2 MiB source, 500 text boxes, 100 PNG layers and
4096 pixels on the longest rendered side. Settings can lower these limits; source
size can increase to 32 MiB within the host read limit. Render size never exceeds
4096. Rendering uses three times the source resolution up to that cap. The parser
also limits input to 20,000 elements, 128 levels of nesting and 16,384 characters
per text segment. Embedded images have a 16 megapixel individual / 32 megapixel
combined limit. Host per-artifact, artifact-count and total-size limits also apply;
the converter additionally caps image layers and final PPTX bytes at 32 MiB.

The pinned requirements were verified on Windows CPython 3.13.5 and 3.11.2.
The renderer uses [resvg_py](https://github.com/baseplate-admin/resvg-py) and the
slide writer uses [python-pptx](https://python-pptx.readthedocs.io/en/latest/).

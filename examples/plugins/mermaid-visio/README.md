# Mermaid Visio

## Optional Graphviz Runtime

With `bundledGraphvizEnabled` enabled (the default), the plugin uses
`vendor/graphviz/win-x64/bin/dot.exe` when that file exists. Otherwise it uses
the configured `dotPath`, which defaults to `dot` on PATH.
Graphviz binaries are not committed to this repository. If installed through the plugin action,
the runtime is stored in the user plugin directory and can be removed by deleting `vendor/graphviz`.

The host installer records the runtime's Eclipse Public License 2.0 notice in
`vendor/graphviz/win-x64/MERMAID_VISIO_GRAPHVIZ_NOTICE.txt`:
https://graphviz.org/license/

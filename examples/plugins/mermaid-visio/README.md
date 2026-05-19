# Mermaid Visio

## Optional Graphviz Runtime

The plugin can use `vendor/graphviz/win-x64/bin/dot.exe` before falling back to system `dot`.
Graphviz binaries are not committed to this repository. If installed through the plugin action,
the runtime is stored in the user plugin directory and can be removed by deleting `vendor/graphviz`.

Graphviz is licensed under the Common Public License:
https://graphviz.gitlab.io/license/

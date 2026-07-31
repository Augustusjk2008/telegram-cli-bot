# Third-Party Notices

This document records third-party components that Orbit Safe Claw directly
uses or bundles. Those components are licensed by their respective copyright
holders under their own terms. Nothing in the Orbit Safe Claw Apache License,
Version 2.0 changes a third party's license.

Inventory baseline: Orbit Safe Claw 1.4.10, audited 2026-07-31 from
`front/package-lock.json`, the built frontend manifest, `requirements.txt`, and
the existing Windows portable artifact. Versions in a future artifact may
differ and must be audited again.

This file is an attribution and review index. Each production frontend build
also generates `front/dist/THIRD_PARTY_LICENSES.txt` from the exact third-party
modules emitted by Vite, reproducing their installed license files and the
KaTeX font OFL terms. The controlling license texts and notices for bundled
runtimes remain in the relevant package metadata, source distribution, or
runtime paths identified below.

## Browser bundle: direct dependencies

The following direct dependencies were found in the current browser build.
Packages grouped in one row use the same listed license family.

| Component and audited version | License and attribution notes |
| --- | --- |
| `@ag-ui/core` 0.0.55 | MIT; upstream `LICENSE`, Copyright (c) 2025. |
| `@codemirror/lang-cpp` 6.0.3, `lang-css` 6.3.1, `lang-html` 6.4.11, `lang-javascript` 6.2.5, `lang-json` 6.0.2, `lang-markdown` 6.5.0, `lang-python` 6.2.1, `language` 6.12.3, `legacy-modes` 6.5.3, `state` 6.7.1, `view` 6.43.6 | MIT; Copyright (C) 2018-2021 Marijn Haverbeke and others. |
| `@lezer/highlight` 1.2.3 | MIT; Copyright (C) 2018 Marijn Haverbeke and others. |
| `@uiw/react-codemirror` 4.25.9 | MIT; Kenny Wong. Installed metadata does not include a standalone license file. |
| `@xterm/addon-attach` 0.12.0, `@xterm/addon-fit` 0.11.0 | MIT; xterm.js authors. |
| `@xterm/xterm` 6.0.0 | MIT; xterm.js authors, SourceLair Private Company, Christopher Jeffrey, Fabrice Bellard, and Microsoft contributors. Preserve the notices in the distributed xterm entry file. |
| `clsx` 2.1.1 | MIT; Copyright (c) Luke Edwards. |
| `tailwind-merge` 3.5.0 | MIT; Copyright (c) 2021 Dany Castillo. |
| `katex` 0.16.45 code and CSS | MIT; Copyright (c) 2013-2020 Khan Academy and other contributors. KaTeX also contains a React-derived utility identified by upstream as Apache-2.0. |
| KaTeX fonts | SIL Open Font License 1.1; Copyright (c) 2009-2010 Design Science, Inc. and Copyright (c) 2014-2018 Khan Academy. Upstream reserved font names include `KaTeX_AMS`, `Caligraphic`, `Fraktur`, `Main`, `Math`, `SansSerif`, `Script`, `Size1`, `Size2`, `Size3`, `Size4`, and `Typewriter`. |
| `react-markdown` 10.1.0 | MIT; Copyright (c) Espen Hovlandsdal. |
| `rehype-katex` 7.0.1, `remark-math` 6.0.0 | MIT; Junyoung Choi. Installed metadata does not include a standalone license file. |
| `remark-gfm` 4.0.1 | MIT; Copyright (c) Titus Wormer. |
| `lucide-react` 0.546.0 | ISC for Lucide (Copyright (c) 2025 Lucide Contributors) and MIT for Feather-derived work (Copyright (c) 2013-2023 Cole Bemis). Preserve the complete upstream `LICENSE`. |
| `mermaid` 11.14.0 | MIT; Copyright (c) 2014-2022 Knut Sveidqvist. |
| `motion` 12.38.0 | MIT; Copyright (c) 2024 Motion B.V. |
| `react` 19.2.4, `react-dom` 19.2.4 | MIT; Copyright (c) Meta Platforms, Inc. and affiliates. |

`@google/genai` 1.48.0 (Apache-2.0), `dotenv` 17.4.1
(BSD-2-Clause), and `express` 4.22.1 (MIT) are declared as production
dependencies but were not imported into the audited browser build.
`@tailwindcss/vite` 4.2.2, `@vitejs/plugin-react` 5.2.0, and `vite` 6.4.2
are build-time tools under the MIT license. They apply when source or build
tooling is redistributed, not as direct browser runtime entries.

The browser bundle also contains transitive dependencies. Examples identified
during this audit include ISC-licensed D3 packages and dual-licensed DOMPurify.
They are included in the generated `THIRD_PARTY_LICENSES.txt`; the hand-written
table above is intentionally a direct-dependency summary, not an artifact-level
software bill of materials.

## Python application dependencies

The Windows portable versions below were read from its installed Python
distribution metadata. Other installation methods resolve the constraints in
`requirements.txt` independently.

| Component and audited version | License and attribution notes |
| --- | --- |
| `python-dotenv` 1.2.2 | BSD-3-Clause; Saurabh Kumar, Ted Tieken, and Jacob Kaplan-Moss. |
| `tomli` | MIT; conditional dependency for Python versions below 3.11 and not installed in the audited Python 3.13 portable runtime. |
| `aiohttp` 3.14.3 | Apache-2.0 AND MIT. Its vendored `llhttp` is MIT, Copyright 2018 Fedor Indutny. Preserve both license files. |
| `PyYAML` 6.0.3 | MIT. |
| `litellm[proxy]` 1.94.0 | MIT; Copyright 2023 Berri AI. |
| `qrcode` 8.2 | BSD-3-Clause, with additional historical MIT attributions and an upstream QR Code trademark notice in its license file. |
| `pygdbmi` 0.11.0.0 | MIT. |
| `pypdf` 6.14.2 | BSD-3-Clause. |
| `tzdata` 2026.3 | Apache-2.0. |
| `ag-ui-protocol` 0.1.19 | MIT; Markus Ecker. Installed metadata does not include a standalone license file. |
| `pywinpty` 3.0.5 | MIT; Windows only. |
| `psutil` 7.2.2 | BSD-3-Clause. |
| `pytest` 9.1.1 | MIT; test dependency currently installed in the portable runtime. |
| `pytest-asyncio` 1.4.0 | Apache-2.0; test dependency currently installed in the portable runtime. |

The portable Python runtime contains transitive distributions in addition to
this direct list. In particular, the audited artifact includes MPL-2.0-covered
material in `certifi`, `orjson`, and `tqdm`. Installed license material is kept
under `runtime/python/Lib/site-packages/*dist-info/`.

## Windows portable bundle

The Windows portable edition aggregates third-party runtimes and tools; those
programs remain separate works under their own licenses.

| Bundled component | License and retained notice location |
| --- | --- |
| Python 3.13.14 embeddable runtime | PSF License 2.0 and bundled notices in `runtime/python/LICENSE.txt`. The patch version is selected at build time and must be rechecked. |
| Node.js 22.17.1 | MIT and bundled dependency notices in `runtime/node/LICENSE`. |
| npm 10.9.2 | Artistic-2.0; distributed as part of the Node.js runtime tree. |
| Corepack 0.33.0 | MIT; distributed as part of the Node.js runtime tree. |
| Git for Windows 2.41.0(3) | GPL-2.0-only for Git, with additional GPLv3/LGPL and component-specific terms in the copied Git distribution. Preserve `tools/git/LICENSE.txt`, `tools/git/ReleaseNotes.html`, and component notices such as `tools/git/mingw64/doc/git-credential-manager/NOTICE`. |
| `@earendil-works/pi-coding-agent`, `pi-agent-core`, `pi-ai`, `pi-tui` 0.74.2 | MIT; Mario Zechner and contributors. The package metadata declares MIT but the audited npm package roots do not carry a standalone license file. |
| `pi-workspace-history` 0.2.2 | MIT; wcldyx. The audited package root does not carry a standalone license file. |
| Legacy `@mariozechner/pi-coding-agent`, `pi-agent-core`, `pi-ai`, `pi-tui` 0.70.6 under `tools/pi-extensions/node_modules` | MIT according to installed metadata. This older tree is currently included in the portable archive and must remain in artifact-specific inventory until packaging removes it. |

Git for Windows is the highest-priority redistribution review item. Copying its
complete installation does not change Orbit Safe Claw's own Apache-2.0 license,
but the portable distributor must independently satisfy all GPL/LGPL notice,
license-text, and corresponding-source obligations for the exact copied
artifact. This document does not constitute a source offer.

## Optional and runtime-downloaded tools

These tools are not preinstalled in all release artifacts. Their terms apply
when a user or installer obtains them:

| Component | Declared or locally recorded license |
| --- | --- |
| Pyright 1.1.410 | MIT. |
| TypeScript Language Server 4.4.1 | Apache-2.0. |
| clangd 22.1.0 | Apache-2.0 WITH LLVM-exception. |

`frpc`/`frps` are not downloaded or bundled by the audited release; Orbit Safe
Claw only invokes a user-configured executable. The installer can optionally
download cloudflared and Codex, but those binaries were not present in the
audited artifacts, so this file does not guess their license or notice content.

## Release compliance checklist

Before publishing each binary release:

1. Confirm the final frontend build generated
   `front/dist/THIRD_PARTY_LICENSES.txt`; the release scripts reject archives
   that omit it.
2. Generate an artifact-specific dependency/SBOM inventory for the Python
   environment, Pi trees, and bundled tool directories, and retain all license
   files shipped inside those runtimes; metadata-only declarations are not
   enough where upstream requires a license text or notice.
3. Recheck KaTeX font/OFL notices, Lucide/Feather dual notices, all frontend
   transitive dependencies, and MPL-covered Python distributions.
4. For the Windows portable artifact, complete and document the Git for Windows
   GPL/LGPL corresponding-source review.
5. Re-audit when any lockfile, requirements file, runtime version, downloaded
   tool version, or packaging script changes.

Upstream license files and package metadata control if this summary conflicts
with them. Questions about redistribution obligations should be reviewed by
qualified legal counsel.

## MIT License text for metadata-only packages

The following terms apply to components identified as MIT above when their
installed package metadata declares MIT but the package root does not include a
standalone license file. Copyright attribution remains as listed in the tables
above and in the upstream package metadata.

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

import type { ReactNode } from "react";

/**
 * File tree icons. Every icon is drawn here as a 16px SVG with its own fixed colour, so types stay
 * recognisable in every theme. Only the plain folder, the generic file and the generic code icon
 * (languages without an icon of their own) follow theme colours, through `currentColor`.
 */

export type FolderIconKind =
  | "default"
  | "src"
  | "test"
  | "docs"
  | "build"
  | "config"
  | "scripts"
  | "tools"
  | "lib"
  | "install"
  | "git"
  | "github"
  | "vscode"
  | "cache"
  | "assets"
  | "public"
  | "include"
  | "modules"
  | "data"
  | "components"
  | "styles"
  | "api";

export type FileIconKind =
  | "generic"
  | "code"
  | "text"
  | "markdown"
  | "json"
  | "xml"
  | "yaml"
  | "toml"
  | "config"
  | "env"
  | "lock"
  | "git"
  | "shell"
  | "powershell"
  | "batch"
  | "python"
  | "notebook"
  | "javascript"
  | "typescript"
  | "react"
  | "html"
  | "css"
  | "sass"
  | "less"
  | "vue"
  | "svelte"
  | "astro"
  | "c"
  | "cpp"
  | "header"
  | "csharp"
  | "go"
  | "rust"
  | "java"
  | "kotlin"
  | "swift"
  | "ruby"
  | "php"
  | "lua"
  | "dart"
  | "cmake"
  | "make"
  | "docker"
  | "node"
  | "license"
  | "pdf"
  | "document"
  | "sheet"
  | "table"
  | "presentation"
  | "image"
  | "vector"
  | "audio"
  | "video"
  | "font"
  | "archive"
  | "database"
  | "binary";

function namesToKind<K extends string>(groups: Array<[K, string]>): Record<string, K> {
  const map: Record<string, K> = Object.create(null);
  for (const [kind, names] of groups) {
    for (const name of names.split(" ")) {
      map[name] = kind;
    }
  }
  return map;
}

const FOLDER_KIND_BY_NAME = namesToKind<FolderIconKind>([
  ["src", "src source sources app core"],
  ["test", "test tests __tests__ spec specs e2e testing"],
  ["docs", "doc docs documentation wiki"],
  ["build", "build dist out output target release debug bin obj .next .nuxt .output"],
  ["config", "config configs conf settings .config etc"],
  ["scripts", "script scripts"],
  ["tools", "tool tools util utils utility utilities helper helpers common shared"],
  ["lib", "lib libs library libraries vendor vendors third_party thirdparty 3rdparty external packages venv .venv"],
  ["install", "install installer installers setup deploy deployment"],
  ["git", ".git"],
  ["github", ".github .gitlab .gitea"],
  ["vscode", ".vscode .idea .vs"],
  ["cache", ".cache .pytest_cache __pycache__ .mypy_cache .ruff_cache .gradle .deps tmp temp .tmp logs log"],
  ["assets", "assets asset images image img icons media resources res"],
  ["public", "public static www web site"],
  ["include", "include includes inc headers"],
  ["modules", "node_modules"],
  ["data", "data db database databases migrations fixtures"],
  ["components", "components component widgets ui views pages screens layouts"],
  ["styles", "styles style css theme themes"],
  ["api", "api apis service services server backend routes controllers"],
]);

const FILE_KIND_BY_NAME = namesToKind<FileIconKind>([
  ["docker", "dockerfile .dockerignore docker-compose.yml docker-compose.yaml compose.yml compose.yaml"],
  ["make", "makefile gnumakefile"],
  ["cmake", "cmakelists.txt"],
  ["license", "license license.md license.txt licence copying notice"],
  ["node", "package.json package-lock.json .npmrc .nvmrc"],
  ["python", "requirements.txt requirements-dev.txt pipfile"],
  [
    "lock",
    "yarn.lock pnpm-lock.yaml bun.lock bun.lockb poetry.lock pdm.lock uv.lock pipfile.lock cargo.lock gemfile.lock composer.lock podfile.lock go.sum",
  ],
  ["shell", ".bashrc .bash_profile .bash_aliases .profile .zshrc .zprofile .zshenv .zlogin .zlogout gradlew mvnw"],
  [
    "config",
    ".editorconfig .yarnrc .prettierrc .prettierignore .eslintrc .eslintignore .stylelintrc .stylelintignore go.mod gemfile podfile meson.build meson.options procfile jenkinsfile",
  ],
]);

const FILE_KIND_BY_EXTENSION = namesToKind<FileIconKind>([
  ["javascript", "js mjs cjs"],
  ["typescript", "ts mts cts"],
  ["react", "jsx tsx"],
  ["vue", "vue"],
  ["svelte", "svelte"],
  ["astro", "astro"],
  ["python", "py pyi pyw"],
  ["notebook", "ipynb"],
  ["c", "c m"],
  ["cpp", "cc cpp cxx cp ipp inl ixx tpp txx mm"],
  ["header", "h hpp hh hxx"],
  ["csharp", "cs csx csproj sln"],
  ["go", "go"],
  ["rust", "rs"],
  ["java", "java"],
  ["kotlin", "kt kts"],
  ["swift", "swift"],
  ["ruby", "rb"],
  ["php", "php"],
  ["lua", "lua"],
  ["dart", "dart"],
  ["code", "scala r zig ex exs hs pl pm fs fsi fsx clj cljs cljc erl hrl ml mli elm vb"],
  ["html", "html htm"],
  ["css", "css"],
  ["sass", "scss sass"],
  ["less", "less"],
  ["shell", "sh bash zsh fish ksh nu"],
  ["powershell", "ps1 psm1 psd1"],
  ["batch", "bat cmd"],
  ["json", "json jsonc json5"],
  ["yaml", "yaml yml"],
  ["toml", "toml"],
  ["xml", "xml plist"],
  ["config", "ini conf cfg properties gradle"],
  ["lock", "lock"],
  ["cmake", "cmake"],
  ["markdown", "md mdx markdown mkd mdown rst"],
  ["text", "txt log text"],
  ["pdf", "pdf"],
  ["document", "doc docx odt rtf pages"],
  ["sheet", "xls xlsx ods"],
  ["table", "csv tsv"],
  ["presentation", "ppt pptx odp key"],
  ["image", "png jpg jpeg gif webp bmp ico avif heic heif tif tiff psd"],
  ["vector", "svg ai eps"],
  ["audio", "mp3 wav flac aac ogg m4a opus aiff mid midi"],
  ["video", "mp4 mov mkv avi webm m4v wmv flv mpeg mpg"],
  ["font", "ttf otf woff woff2 eot fon"],
  ["archive", "zip tar gz tgz rar 7z bz2 xz lz lz4 cab iso zst"],
  ["database", "sql db db3 sqlite sqlite3 mdb accdb parquet duckdb"],
  ["binary", "exe dll so dylib o a obj lib bin class pyc wasm"],
]);

function fileExtension(name: string) {
  const lastDotIndex = name.lastIndexOf(".");
  if (lastDotIndex <= 0 || lastDotIndex === name.length - 1) {
    return "";
  }
  return name.slice(lastDotIndex + 1);
}

export function getFolderIconKind(name: string): FolderIconKind {
  return FOLDER_KIND_BY_NAME[name.trim().toLowerCase()] ?? "default";
}

export function getFileIconKind(name: string): FileIconKind {
  const normalized = name.trim().toLowerCase();
  if (normalized.startsWith(".env")) {
    return "env";
  }
  if (normalized.startsWith(".git")) {
    return "git";
  }
  const byName = FILE_KIND_BY_NAME[normalized];
  if (byName) {
    return byName;
  }
  const byExtension = FILE_KIND_BY_EXTENSION[fileExtension(normalized)];
  if (byExtension) {
    return byExtension;
  }
  // Extension-less dotfiles such as `.babelrc` are tool configuration.
  if (normalized.startsWith(".") && normalized.endsWith("rc")) {
    return "config";
  }
  return "generic";
}

const TILE_FONT = "'Segoe UI', 'Helvetica Neue', Arial, 'Noto Sans', sans-serif";

function Svg({ children }: { children: ReactNode }) {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4" fill="none" strokeLinecap="round" strokeLinejoin="round">
      {children}
    </svg>
  );
}

/** A rounded colour tile with a one- to three-letter label. */
function tile(label: string, background: string, foreground = "#fff") {
  const fontSize = label.length >= 3 ? 6.4 : label.length === 2 ? 8 : 10.5;
  return (
    <Svg>
      <rect x="1" y="1" width="14" height="14" rx="3" fill={background} />
      <text
        x="8"
        y="8"
        dy="0.36em"
        textAnchor="middle"
        fontFamily={TILE_FONT}
        fontSize={fontSize}
        fontWeight="800"
        fill={foreground}
        {...(label.length >= 3 ? { textLength: 11.4, lengthAdjust: "spacingAndGlyphs" as const } : {})}
      >
        {label}
      </text>
    </Svg>
  );
}

/** A tile carrying a terminal prompt; the colour tells the shell family apart. */
function promptTile(background: string) {
  return (
    <Svg>
      <rect x="1" y="1" width="14" height="14" rx="3" fill={background} />
      <path d="M4.2 5.3 7 8l-2.8 2.7M8.4 10.9h3.5" stroke="#fff" strokeWidth="1.5" />
    </Svg>
  );
}

function page(color: string, lines: boolean) {
  return (
    <Svg>
      <path
        d="M4.5 1.5h4.9L13 5.1V13a1.5 1.5 0 0 1-1.5 1.5h-7A1.5 1.5 0 0 1 3 13V3a1.5 1.5 0 0 1 1.5-1.5z"
        fill={color}
        fillOpacity="0.14"
        stroke={color}
        strokeWidth="1.2"
      />
      <path d="M9.2 1.8v2.5a1 1 0 0 0 1 1h2.5" stroke={color} strokeWidth="1.2" />
      {lines ? <path d="M5.6 8.4h4.8M5.6 10.9h3.2" stroke={color} strokeWidth="1.2" /> : null}
    </Svg>
  );
}

function gear(color: string) {
  return (
    <Svg>
      <circle cx="8" cy="8" r="4.9" stroke={color} strokeWidth="2.2" strokeDasharray="1.92 1.93" strokeLinecap="butt" />
      <circle cx="8" cy="8" r="3" stroke={color} strokeWidth="2" />
    </Svg>
  );
}

const FILE_ICONS: Record<FileIconKind, () => ReactNode> = {
  generic: () => page("currentColor", false),
  text: () => page("#8496A8", true),
  code: () => (
    <Svg>
      <path d="M5.8 4.4 2.4 8l3.4 3.6M10.2 4.4 13.6 8l-3.4 3.6" stroke="currentColor" strokeWidth="1.6" />
    </Svg>
  ),
  markdown: () => (
    <Svg>
      <rect x="1" y="2.5" width="14" height="11" rx="2.4" fill="#3D8FE4" />
      <path d="M3.5 10.4V5.7l2 2.4 2-2.4v4.7M11.2 5.6v4.3M9.5 8.5l1.7 1.9 1.7-1.9" stroke="#fff" strokeWidth="1.3" />
    </Svg>
  ),
  json: () => (
    <Svg>
      <path
        d="M6.2 2.6c-1.5 0-2 .7-2 1.9v1.6c0 .9-.5 1.5-1.5 1.9 1 .4 1.5 1 1.5 1.9v1.6c0 1.2.5 1.9 2 1.9M9.8 2.6c1.5 0 2 .7 2 1.9v1.6c0 .9.5 1.5 1.5 1.9-1 .4-1.5 1-1.5 1.9v1.6c0 1.2-.5 1.9-2 1.9"
        stroke="#F2A922"
        strokeWidth="1.6"
      />
    </Svg>
  ),
  xml: () => (
    <Svg>
      <path d="M5.2 4.8 2.2 8l3 3.2M10.8 4.8l3 3.2-3 3.2M9.2 3.4 6.8 12.6" stroke="#F2792E" strokeWidth="1.5" />
    </Svg>
  ),
  yaml: () => tile("Y", "#D9534F"),
  toml: () => tile("T", "#9A5A32"),
  config: () => gear("#7F93A8"),
  env: () => tile("ENV", "#E6CF3C", "#3A3200"),
  lock: () => (
    <Svg>
      <path d="M5.5 7.2V5.3a2.5 2.5 0 0 1 5 0v1.9" stroke="#8A9AAC" strokeWidth="1.5" />
      <rect x="3.6" y="7" width="8.8" height="6.8" rx="1.6" fill="#8A9AAC" />
      <circle cx="8" cy="10.4" r="1.1" fill="#fff" />
    </Svg>
  ),
  git: () => (
    <Svg>
      <path d="M8 1.9 14.1 8 8 14.1 1.9 8z" fill="#F0513A" stroke="#F0513A" strokeWidth="1.6" />
      <path d="M8 5.2v5.6M8 6.7l2.2 2" stroke="#fff" strokeWidth="1.1" />
      <circle cx="8" cy="5" r="1.05" fill="#fff" />
      <circle cx="8" cy="11" r="1.05" fill="#fff" />
      <circle cx="10.4" cy="8.9" r="1.05" fill="#fff" />
    </Svg>
  ),
  shell: () => promptTile("#46A758"),
  powershell: () => promptTile("#2E86DE"),
  batch: () => promptTile("#B06AA4"),
  python: () => (
    <svg viewBox="0 0 20 20" className="h-4 w-4">
      <path fill="#3776AB" d="M10 2.2H7.45A3.25 3.25 0 0 0 4.2 5.45v2.1h5.15c1 0 1.8.8 1.8 1.8v1.55h1.4a3.25 3.25 0 0 0 3.25-3.25V5.45A3.25 3.25 0 0 0 12.65 2.2z" />
      <circle cx="8.1" cy="4.75" r=".8" fill="#fff" />
      <path fill="#FFD43B" d="M10 17.8h2.55a3.25 3.25 0 0 0 3.25-3.25V12.4h-5.15a1.8 1.8 0 0 0-1.8 1.8v1.55H7.45A3.25 3.25 0 0 1 4.2 12.5v2.05a3.25 3.25 0 0 0 3.25 3.25z" />
      <circle cx="11.9" cy="15.25" r=".8" fill="#fff" />
    </svg>
  ),
  notebook: () => tile("NB", "#F37726"),
  javascript: () => tile("JS", "#F0DB4F", "#323330"),
  typescript: () => tile("TS", "#3178C6"),
  react: () => (
    <Svg>
      <g stroke="#14B4D6" strokeWidth="1">
        <ellipse cx="8" cy="8" rx="6.6" ry="2.6" />
        <ellipse cx="8" cy="8" rx="6.6" ry="2.6" transform="rotate(60 8 8)" />
        <ellipse cx="8" cy="8" rx="6.6" ry="2.6" transform="rotate(120 8 8)" />
      </g>
      <circle cx="8" cy="8" r="1.35" fill="#14B4D6" />
    </Svg>
  ),
  html: () => (
    <Svg>
      <rect x="1" y="1" width="14" height="14" rx="3" fill="#E5532D" />
      <path d="M6.3 5.2 3.7 8l2.6 2.8M9.7 5.2 12.3 8l-2.6 2.8" stroke="#fff" strokeWidth="1.5" />
    </Svg>
  ),
  css: () => tile("#", "#2D7DD2"),
  sass: () => tile("S", "#CF649A"),
  less: () => tile("L", "#2A4F84"),
  vue: () => tile("V", "#41B883"),
  svelte: () => tile("S", "#FF3E00"),
  astro: () => tile("A", "#BC52EE"),
  c: () => tile("C", "#5C7CDB"),
  cpp: () => tile("C++", "#0B6CBF"),
  header: () => tile("H", "#9C6ADE"),
  csharp: () => tile("C#", "#7B3FA0"),
  go: () => tile("GO", "#00ACD7"),
  rust: () => tile("RS", "#C4532D"),
  java: () => tile("J", "#E76F00"),
  kotlin: () => tile("K", "#7F52FF"),
  swift: () => tile("S", "#F05138"),
  ruby: () => tile("RB", "#CC342D"),
  php: () => tile("PHP", "#777BB4"),
  lua: () => tile("LUA", "#2C2D72"),
  dart: () => tile("D", "#0175C2"),
  cmake: () => (
    <Svg>
      <path d="M8 1.7 1.5 14h3.6L8 8.2z" fill="#2A6FDB" />
      <path d="M8 1.7 14.5 14l-4-3.4L8 8.2z" fill="#E5413A" />
      <path d="M5.1 14h9.4l-4-3.4L8 8.2z" fill="#3DAE49" />
    </Svg>
  ),
  make: () => tile("MK", "#6C8A5E"),
  docker: () => (
    <Svg>
      <g fill="#1D91EC">
        <rect x="2.3" y="6.6" width="2.9" height="2.7" rx=".5" />
        <rect x="5.8" y="6.6" width="2.9" height="2.7" rx=".5" />
        <rect x="9.3" y="6.6" width="2.9" height="2.7" rx=".5" />
        <rect x="5.8" y="3.3" width="2.9" height="2.7" rx=".5" />
        <path d="M1.4 10h13.2c0 2.2-2.3 3.9-5.6 3.9H6.7c-3 0-5.3-1.7-5.3-3.9z" />
      </g>
    </Svg>
  ),
  node: () => (
    <Svg>
      <path d="M8 1.6 13.6 4.8v6.4L8 14.4 2.4 11.2V4.8z" fill="#5FA04E" stroke="#5FA04E" strokeWidth="1" />
      <path d="M6 10.3V5.7l4 4.6V5.7" stroke="#fff" strokeWidth="1.3" />
    </Svg>
  ),
  license: () => (
    <Svg>
      <path d="M5.4 9.2 4.6 14.4 8 12.6l3.4 1.8-.8-5.2z" fill="#C98A1B" />
      <circle cx="8" cy="6.2" r="4.4" fill="#E9AE2C" />
      <path d="M6 6.3l1.4 1.4L10.1 5" stroke="#fff" strokeWidth="1.3" />
    </Svg>
  ),
  pdf: () => tile("PDF", "#E5252A"),
  document: () => tile("W", "#2B7CD3"),
  sheet: () => tile("X", "#1F9D55"),
  table: () => (
    <Svg>
      <rect x="1.6" y="2.6" width="12.8" height="10.8" rx="1.8" fill="#2E9E5B" />
      <path d="M1.6 6.3h12.8M1.6 9.8h12.8M6 2.6v10.8M10.2 2.6v10.8" stroke="#fff" strokeWidth=".9" strokeLinecap="butt" />
    </Svg>
  ),
  presentation: () => tile("P", "#D8502D"),
  image: () => (
    <Svg>
      <rect x="1.6" y="2.6" width="12.8" height="10.8" rx="1.9" fill="#26A892" />
      <circle cx="5.3" cy="6.1" r="1.3" fill="#fff" />
      <path d="M3.1 11.9l3.1-3.5 2 2.1 1.8-2.2 2.9 3.6z" fill="#fff" />
    </Svg>
  ),
  vector: () => (
    <Svg>
      <rect x="1.6" y="2.6" width="12.8" height="10.8" rx="1.9" fill="#F5A623" />
      <path d="M4.2 10.6c1.2-4.4 6.4-4.4 7.6 0" stroke="#fff" strokeWidth="1.2" />
      <circle cx="4.2" cy="10.6" r="1.2" fill="#fff" />
      <circle cx="11.8" cy="10.6" r="1.2" fill="#fff" />
      <circle cx="8" cy="6.1" r="1.2" fill="#fff" />
    </Svg>
  ),
  audio: () => (
    <Svg>
      <path d="M6.4 11.6V4l6-1.5v7.7" stroke="#E0527A" strokeWidth="1.5" />
      <ellipse cx="4.8" cy="11.7" rx="1.9" ry="1.6" fill="#E0527A" />
      <ellipse cx="10.8" cy="10.3" rx="1.9" ry="1.6" fill="#E0527A" />
    </Svg>
  ),
  video: () => (
    <Svg>
      <rect x="1.5" y="3" width="13" height="10" rx="2.2" fill="#F28C28" />
      <path d="M6.6 5.7v4.6L10.6 8z" fill="#fff" stroke="#fff" strokeWidth=".8" />
    </Svg>
  ),
  font: () => (
    <Svg>
      <text x="8" y="8" dy="0.36em" textAnchor="middle" fontFamily={TILE_FONT} fontSize="10.5" fontWeight="800" fill="#E5483F">
        Aa
      </text>
    </Svg>
  ),
  archive: () => (
    <Svg>
      <rect x="2.4" y="1.6" width="11.2" height="12.8" rx="1.8" fill="#B79A2E" />
      <path d="M8 2.6v1.3M8 5.2v1.3M8 7.8v1.3" stroke="#fff" strokeWidth="1.7" strokeLinecap="butt" />
      <rect x="6.7" y="10.2" width="2.6" height="2.6" rx=".6" fill="#fff" />
    </Svg>
  ),
  database: () => (
    <Svg>
      <path d="M3 4.3v7.4c0 1.2 2.2 2.2 5 2.2s5-1 5-2.2V4.3z" fill="#DFA226" />
      <ellipse cx="8" cy="4.3" rx="5" ry="2.2" fill="#F0BC4A" />
      <path d="M3 8c0 1.2 2.2 2.2 5 2.2s5-1 5-2.2" stroke="#fff" strokeWidth=".9" />
    </Svg>
  ),
  binary: () => tile("01", "#6B7888"),
};

type FolderStyle = { color: string; glyph: ReactNode };

/** Glyphs are drawn around (0,0) in a 6px box and moved onto the folder front. */
const FOLDER_STYLES: Record<Exclude<FolderIconKind, "default">, FolderStyle> = {
  src: { color: "#43A047", glyph: <path d="M-1.1-1.9-3 0l1.9 1.9M1.1-1.9 3 0 1.1 1.9" /> },
  test: { color: "#0E9AA7", glyph: <path d="M-2.7.1-.9 1.9 2.8-1.8" /> },
  docs: { color: "#2D7FE0", glyph: <path d="M-2.6-1.8h5.2M-2.6 0h5.2M-2.6 1.8h3.2" /> },
  build: { color: "#EF7B1A", glyph: <path d="M-2.6-1.1 0-2.4l2.6 1.3v2.5L0 2.6-2.6 1.4zM-2.6-1.1 0 .2l2.6-1.3M0 .2v2.4" strokeWidth="1" /> },
  config: {
    color: "#5C6BC0",
    glyph: (
      <>
        <path d="M-3-1.4h6M-3 1.4h6" />
        <circle cx="-1" cy="-1.4" r="1.15" fill="#fff" stroke="none" />
        <circle cx="1.2" cy="1.4" r="1.15" fill="#fff" stroke="none" />
      </>
    ),
  },
  scripts: { color: "#7E57C2", glyph: <path d="M-2.9-1.8-.9 0l-2 1.8M.5 1.9h2.5" /> },
  tools: {
    color: "#D98A1E",
    glyph: (
      <>
        <circle r="2.5" strokeWidth="1.3" strokeDasharray="0.98 0.98" strokeLinecap="butt" />
        <circle r="1.5" strokeWidth="1.1" />
      </>
    ),
  },
  lib: { color: "#9E9D24", glyph: <path d="M-2.5-2.2v4.4M-.3-2.2v4.4M1.5-2 2.9 2.2" /> },
  install: { color: "#26A69A", glyph: <path d="M0-2.6V.9M-1.9-.8 0 1.1l1.9-1.9M-2.7 2.6h5.4" /> },
  git: {
    color: "#F0513A",
    glyph: (
      <>
        <path d="M-1.5-1.2v2.4M-1.5 .5c0-1.2 1.2-1.3 2.4-1.3" strokeWidth="1" />
        <circle cx="-1.5" cy="-1.9" r=".95" fill="#fff" stroke="none" />
        <circle cx="-1.5" cy="1.9" r=".95" fill="#fff" stroke="none" />
        <circle cx="1.7" cy="-.8" r=".95" fill="#fff" stroke="none" />
      </>
    ),
  },
  github: {
    color: "#546E7A",
    glyph: (
      <>
        <path d="M-1.5-1.2v2.4M-1.5 .5c0-1.2 1.2-1.3 2.4-1.3" strokeWidth="1" />
        <circle cx="-1.5" cy="-1.9" r=".95" fill="#fff" stroke="none" />
        <circle cx="-1.5" cy="1.9" r=".95" fill="#fff" stroke="none" />
        <circle cx="1.7" cy="-.8" r=".95" fill="#fff" stroke="none" />
      </>
    ),
  },
  vscode: { color: "#2196F3", glyph: <path d="M2.3-2.4-2.4 0l4.7 2.4zM2.3-2.4v4.8" strokeWidth="1.1" /> },
  cache: {
    color: "#78909C",
    glyph: (
      <>
        <circle r="2.5" strokeWidth="1.1" />
        <path d="M0-1.3V0l1 .8" strokeWidth="1" />
      </>
    ),
  },
  assets: {
    color: "#AB47BC",
    glyph: (
      <>
        <path d="M-3 2.3-.9-.4.7 1.3l1-1 1.4 2z" fill="#fff" strokeWidth=".6" />
        <circle cx="1.7" cy="-1.5" r=".9" fill="#fff" stroke="none" />
      </>
    ),
  },
  public: {
    color: "#29A3E0",
    glyph: (
      <>
        <circle r="2.6" strokeWidth="1" />
        <path d="M-2.6 0h5.2M0-2.6c-1.5 1.6-1.5 3.6 0 5.2M0-2.6c1.5 1.6 1.5 3.6 0 5.2" strokeWidth=".8" />
      </>
    ),
  },
  include: { color: "#4D8FD6", glyph: <path d="M-.8-2.4-1.5 2.4M1.6-2.4.9 2.4M-2.6-.8h5.4M-2.9.9h5.4" strokeWidth="1" /> },
  modules: { color: "#7CB342", glyph: <path d="M0-2.7 2.4-1.35v2.7L0 2.7-2.4 1.35v-2.7z" strokeWidth="1.1" /> },
  data: {
    color: "#8D6E63",
    glyph: (
      <>
        <ellipse cy="-1.6" rx="2.5" ry="1" strokeWidth="1" />
        <path d="M-2.5-1.6v3.2c0 .6 1.1 1 2.5 1s2.5-.4 2.5-1v-3.2M-2.5 0c0 .6 1.1 1 2.5 1s2.5-.4 2.5-1" strokeWidth="1" />
      </>
    ),
  },
  components: {
    color: "#F06292",
    glyph: (
      <g fill="#fff" stroke="none">
        <rect x="-2.7" y="-2.5" width="2.3" height="2.3" rx=".5" />
        <rect x=".4" y="-2.5" width="2.3" height="2.3" rx=".5" />
        <rect x="-2.7" y=".4" width="2.3" height="2.3" rx=".5" />
        <rect x=".4" y=".4" width="2.3" height="2.3" rx=".5" />
      </g>
    ),
  },
  styles: {
    color: "#E0478A",
    glyph: <path d="M0-2.7C1.6-.9 2.3.1 2.3 1a2.3 2.3 0 0 1-4.6 0C-2.3.1-1.6-.9 0-2.7z" fill="#fff" stroke="none" />,
  },
  api: {
    color: "#FF7043",
    glyph: (
      <>
        <rect x="-2.8" y="-2.5" width="5.6" height="2" rx=".6" strokeWidth="1" />
        <rect x="-2.8" y=".5" width="5.6" height="2" rx=".6" strokeWidth="1" />
      </>
    ),
  },
};

const FOLDER_CLOSED_PATH = "M1.5 4A1.5 1.5 0 0 1 3 2.5h3.2c.4 0 .78.16 1.06.44L8.3 4H13a1.5 1.5 0 0 1 1.5 1.5V12a1.5 1.5 0 0 1-1.5 1.5H3A1.5 1.5 0 0 1 1.5 12z";
const FOLDER_OPEN_FRONT_PATH = "M3.55 7.1a1.1 1.1 0 0 1 1.05-.8h10a.75.75 0 0 1 .72.96l-1.5 5.2a1.45 1.45 0 0 1-1.4 1.04H2.3a.75.75 0 0 1-.72-.96z";

export function FolderIcon({ kind, open }: { kind: FolderIconKind; open: boolean }) {
  const style = kind === "default" ? null : FOLDER_STYLES[kind];
  return (
    <span
      aria-hidden="true"
      data-icon={open ? "folder-open" : "folder-closed"}
      data-folder-kind={kind}
      className="inline-flex h-4 w-4 shrink-0 items-center justify-center text-[var(--file-tree-folder,var(--status-warning))]"
      style={style ? { color: style.color } : undefined}
    >
      <Svg>
        {open ? (
          <>
            <path d={FOLDER_CLOSED_PATH} fill="currentColor" fillOpacity="0.5" />
            <path d={FOLDER_OPEN_FRONT_PATH} fill="currentColor" />
          </>
        ) : (
          <path d={FOLDER_CLOSED_PATH} fill="currentColor" />
        )}
        {style ? (
          <g transform={open ? "translate(8.4 10)" : "translate(8 8.9)"} stroke="#fff" strokeWidth="1.2" strokeOpacity="0.95" fillOpacity="0.95">
            {style.glyph}
          </g>
        ) : null}
      </Svg>
    </span>
  );
}

export function FileIcon({ kind }: { kind: FileIconKind }) {
  const colorClass = kind === "code"
    ? "text-[var(--file-tree-code-icon,var(--muted))]"
    : "text-[var(--file-tree-muted,var(--muted))]";
  return (
    <span
      aria-hidden="true"
      data-icon={`file-${kind}`}
      className={`inline-flex h-4 w-4 shrink-0 select-none items-center justify-center ${colorClass}`}
    >
      {FILE_ICONS[kind]()}
    </span>
  );
}

#!/usr/bin/env python3
"""Print a Markdown map of a project folder or archive.

Usage:
    python inventory.py PATH [--depth 3] [--max-files 25] [--max-lines 40] [--out map.md]

PATH can be a directory, .zip, .tar, .tar.gz or .tgz. Standard library only.

The output is a map for reading the project, not a verdict. The heuristics miss
frameworks they do not know, so open a file before teaching from it. Secrets are
never printed: .env files are not read, and suspicious assignments are reported
as file:line plus variable name only.
"""

import argparse
import ast
import json
import os
import posixpath
import re
import sys
import tarfile
import tempfile
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

IGNORE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".idea", ".vscode",
    "dist", "build", ".next", ".nuxt", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "target", ".gradle", ".tox", "coverage", ".ipynb_checkpoints",
    "site-packages", ".cache", ".terraform", "__MACOSX",
}
LANG = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".java": "Java", ".kt": "Kotlin",
    ".go": "Go", ".rs": "Rust", ".c": "C", ".h": "C/C++", ".cpp": "C++",
    ".cs": "C#", ".php": "PHP", ".rb": "Ruby", ".swift": "Swift", ".r": "R",
    ".sql": "SQL", ".sh": "Shell", ".html": "HTML", ".css": "CSS", ".vue": "Vue",
    ".ipynb": "Notebook", ".dart": "Dart", ".scala": "Scala",
}
JS_EXT = {".js", ".jsx", ".mjs", ".ts", ".tsx"}
DOC_EXT = {".md", ".rst", ".txt", ".pdf", ".docx", ".pptx", ".odt"}
DATA_EXT = {
    ".csv", ".tsv", ".parquet", ".xlsx", ".xls", ".json", ".jsonl", ".sqlite",
    ".db", ".pkl", ".joblib", ".h5", ".hdf5", ".pt", ".pth", ".onnx", ".npy",
    ".npz", ".feather", ".pb", ".safetensors",
}
ENTRY_NAMES = {
    "main.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "run.py", "server.py",
    "cli.py", "__main__.py", "index.js", "server.js", "app.js", "main.js",
    "main.ts", "index.ts", "server.ts", "app.ts",
}
CONFIG_NAMES = {
    "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "pipfile",
    "environment.yml", "package.json", "pom.xml", "build.gradle", "go.mod",
    "cargo.toml", "dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "makefile", ".env.example", "dbt_project.yml", "profiles.yml", "procfile",
    "vercel.json", "netlify.toml", "tox.ini", "pytest.ini", "conftest.py",
}
NODE_BUILTIN = {
    "fs", "path", "http", "https", "os", "util", "events", "stream", "crypto",
    "url", "child_process", "zlib", "buffer", "assert", "net", "readline",
    "querystring", "timers", "process", "worker_threads", "cluster", "tls",
}
STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {
    "os", "sys", "re", "json", "math", "time", "datetime", "typing", "pathlib",
    "collections", "itertools", "functools", "logging", "random", "argparse",
    "subprocess", "threading", "asyncio", "csv", "io", "uuid", "hashlib",
    "pickle", "copy", "dataclasses", "enum", "abc", "unittest", "sqlite3",
    "urllib", "http", "socket", "string", "statistics", "tempfile", "shutil",
    "glob", "warnings", "traceback", "inspect", "contextlib", "base64",
    "zipfile", "tarfile", "gzip", "pprint", "textwrap", "decimal", "operator",
    "queue", "heapq", "bisect", "secrets", "platform", "signal", "struct",
    "types", "weakref", "configparser", "email", "html", "xml", "ssl", "ast",
    "__future__",
}
HTTP_VERBS = {"get", "post", "put", "delete", "patch", "head", "options"}
MODEL_BASES = {"Base", "DeclarativeBase", "SQLModel", "Document", "Schema", "BaseModel", "Model"}

JS_ROUTE = re.compile(
    r"""\b(?:app|router|[A-Za-z_]*[Rr]outer|server|api)\.(get|post|put|delete|patch|all)\(\s*(['"`])(/[^'"`]*)\2"""
)
JAVA_ROUTE = re.compile(r'@(Get|Post|Put|Delete|Patch|Request)Mapping\(\s*(?:value\s*=\s*|path\s*=\s*)?"([^"]*)"')
JS_IMPORT = re.compile(
    r"""(?:\bimport\s+(?:[\w*{}\s,$]+?\s+from\s+)?|\brequire\(\s*|\bimport\(\s*)['"]([^'"]+)['"]"""
)
JS_SYMS = re.compile(
    r"""^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?(?:function\s*\*?\s*(\w+)|class\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>)""",
    re.M,
)
SQL_TABLE = re.compile(r"""(?i)create\s+(?:or\s+replace\s+)?table\s+(?:if\s+not\s+exists\s+)?([\w."`\[\]]+)""")
ENV_PATTERNS = [
    re.compile(r"""(?:os\.getenv|os\.environ\.get|environ\.get|getenv)\(\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]"""),
    re.compile(r"""os\.environ\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]\s*\]"""),
    re.compile(r"""process\.env\.([A-Za-z_][A-Za-z0-9_]*)"""),
    re.compile(r"""process\.env\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]\s*\]"""),
    re.compile(r"""st\.secrets\[\s*['"]([^'"]+)['"]\s*\]"""),
]
SECRET_NAME = re.compile(
    r"""(?i)\b([A-Za-z0-9_]*(?:api[_-]?key|secret|token|passwd|password|access[_-]?key|private[_-]?key)[A-Za-z0-9_]*)\b\s*[:=]\s*(['"])([^'"\s]{8,})\2"""
)
SECRET_VALUE = re.compile(r"""\b(sk-[A-Za-z0-9_\-]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9\-]{10,})""")
PLACEHOLDER = re.compile(r"(?i)your|example|changeme|xxx|placeholder|dummy|<|\$\{|\{\{")
MOCK_SIGNS = re.compile(r"unittest\.mock|\bMagicMock\b|monkeypatch|\bmocker\b|jest\.mock|sinon|requests_mock|httpretty|\bpatch\(")


# ---------------------------------------------------------------- input


def extract_archive(path):
    tmp = Path(tempfile.mkdtemp(prefix="inventory_"))
    root = tmp.resolve()
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            if sum(i.file_size for i in z.infolist()) > 800_000_000:
                sys.exit("Archive expands to more than 800 MB. Extract the part you need and pass that folder.")
            for info in z.infolist():
                target = (root / info.filename).resolve()
                if target != root and root not in target.parents:
                    continue
                z.extract(info, root)
    elif tarfile.is_tarfile(path):
        with tarfile.open(path) as t:
            safe = []
            for m in t.getmembers():
                target = (root / m.name).resolve()
                if (target == root or root in target.parents) and (m.isfile() or m.isdir()):
                    safe.append(m)
            try:
                t.extractall(root, members=safe, filter="data")
            except TypeError:
                t.extractall(root, members=safe)
    else:
        sys.exit(f"Not a directory or a supported archive: {path}")
    kids = [k for k in tmp.iterdir() if k.name != "__MACOSX"]
    return kids[0] if len(kids) == 1 and kids[0].is_dir() else tmp


def keep_dir(d):
    n = d.name
    return n not in IGNORE_DIRS and not n.endswith(".egg-info") and not (d / "pyvenv.cfg").exists()


def collect_files(root, cap=20000):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dp = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if keep_dir(dp / d))
        for f in sorted(filenames):
            out.append(dp / f)
        if len(out) >= cap:
            break
    return out


def size_of(p):
    try:
        return p.stat().st_size
    except OSError:
        return 0


def load_text(p, limit):
    try:
        if p.stat().st_size > limit:
            return None
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def is_secret_env_file(name):
    return name == ".env" or (name.startswith(".env.") and not name.endswith((".example", ".sample", ".template")))


def is_test_file(r):
    parts = r.lower().split("/")
    n = parts[-1]
    return (
        n.startswith("test_") or n.endswith("_test.py") or ".test." in n or ".spec." in n
        or n == "conftest.py" or any(p in {"tests", "test", "__tests__", "spec"} for p in parts[:-1])
    )


# ---------------------------------------------------------------- python helpers


def const_str(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def ast_text(node):
    try:
        return ast.unparse(node)
    except Exception:
        return getattr(node, "id", "?")


def args_text(fn):
    a = fn.args
    names = [x.arg for x in a.posonlyargs + a.args]
    if a.vararg:
        names.append("*" + a.vararg.arg)
    names += [x.arg for x in a.kwonlyargs]
    if a.kwarg:
        names.append("**" + a.kwarg.arg)
    return ", ".join(names)


def py_routes(tree, rel):
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in node.decorator_list:
            if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)):
                continue
            attr = d.func.attr.lower()
            if attr not in HTTP_VERBS and attr not in {"route", "websocket", "api_route"}:
                continue
            path = const_str(d.args[0]) if d.args else None
            if path is None:
                for kw in d.keywords:
                    if kw.arg in ("path", "rule"):
                        path = const_str(kw.value)
            if path is None or not path.startswith("/"):
                continue
            methods = [attr.upper()] if attr in HTTP_VERBS else ["GET"]
            for kw in d.keywords:
                if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple, ast.Set)):
                    methods = [const_str(e).upper() for e in kw.value.elts if const_str(e)] or methods
            if attr == "websocket":
                methods = ["WS"]
            found.append((",".join(methods), path, node.name, f"{rel}:{node.lineno}"))
    return found


def django_routes(tree, rel):
    found = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in {"path", "re_path", "url"} and node.args
        ):
            p = const_str(node.args[0])
            if p is None:
                continue
            view = ast_text(node.args[1]) if len(node.args) > 1 else "?"
            found.append(("ANY", "/" + p.lstrip("^/").rstrip("$"), view, f"{rel}:{node.lineno}"))
    return found


def py_models(tree, rel):
    out = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        bases = [ast_text(b) for b in node.bases]
        if not any(b.split(".")[-1] in MODEL_BASES or b.endswith("Model") for b in bases):
            continue
        fields = []
        for st in node.body:
            if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                fields.append(st.target.id)
            elif (
                isinstance(st, ast.Assign) and len(st.targets) == 1
                and isinstance(st.targets[0], ast.Name) and isinstance(st.value, ast.Call)
            ):
                fields.append(st.targets[0].id)
        out.append((node.name, bases, fields[:12], f"{rel}:{node.lineno}"))
    return out


def py_outline(tree):
    doc = (ast.get_docstring(tree) or "").strip().splitlines()
    items = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases = ", ".join(ast_text(b) for b in node.bases)
            items.append(f"class {node.name}({bases}) L{node.lineno}")
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    items.append(f"    .{sub.name}({args_text(sub)}) L{sub.lineno}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            items.append(f"{kind} {node.name}({args_text(node)}) L{node.lineno}")
    return (doc[0][:120] if doc else ""), items


def py_imports(tree):
    mods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.append((a.name, 0, []))
        elif isinstance(node, ast.ImportFrom):
            mods.append((node.module or "", node.level, [a.name for a in node.names]))
    return mods


def import_candidates(mod, level, names, pkg):
    if level:
        base = pkg[: max(len(pkg) - (level - 1), 0)]
        head = ".".join(base + ([mod] if mod else []))
    else:
        head = mod
    cands = [head] if head else []
    for n in names:
        if n != "*":
            cands.append(f"{head}.{n}" if head else n)
    return cands


# ---------------------------------------------------------------- js helpers


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def js_pkg_name(spec):
    if spec.startswith("node:"):
        return None
    parts = spec.split("/")
    name = "/".join(parts[:2]) if spec.startswith("@") else parts[0]
    return None if name in NODE_BUILTIN else name


def resolve_js(spec, rel, known):
    base = posixpath.normpath(posixpath.join(posixpath.dirname(rel), spec))
    for ext in ("", ".js", ".jsx", ".ts", ".tsx", ".mjs"):
        if base + ext in known:
            return base + ext
    for ext in (".js", ".jsx", ".ts", ".tsx"):
        if f"{base}/index{ext}" in known:
            return f"{base}/index{ext}"
    return None


# ---------------------------------------------------------------- manifests, notebooks


def parse_requirements(text):
    names = []
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if not line or line.startswith(("-", "git+", "http")):
            continue
        m = re.match(r"[A-Za-z0-9_.\-]+", line)
        if m:
            names.append(m.group(0))
    return names


def parse_pyproject(text):
    try:
        import tomllib

        d = tomllib.loads(text)
        deps = list(d.get("project", {}).get("dependencies", []))
        deps += list(d.get("tool", {}).get("poetry", {}).get("dependencies", {}).keys())
        out = []
        for x in deps:
            m = re.match(r"[A-Za-z0-9_.\-]+", x)
            if m:
                out.append(m.group(0))
        return out
    except Exception:
        return []


def notebook_info(text):
    try:
        nb = json.loads(text)
    except ValueError:
        return None
    code, md = [], []
    for c in nb.get("cells", []):
        src = c.get("source", "")
        src = "".join(src) if isinstance(src, list) else src
        (code if c.get("cell_type") == "code" else md).append((c, src))
    heads = []
    for _, src in md:
        heads += [ln.strip() for ln in src.splitlines() if ln.startswith("#")]
    libs = set()
    for _, src in code:
        for m in re.finditer(r"^\s*(?:from|import)\s+([A-Za-z_]\w*)", src, re.M):
            libs.add(m.group(1))
    has_out = any(c.get("outputs") for c, _ in code)
    return len(code), len(md), has_out, heads[:12], libs


def first_line(p, n=240):
    try:
        with open(p, "rb") as f:
            return f.readline(n * 2).decode("utf-8", "replace").strip()[:n]
    except OSError:
        return ""


# ---------------------------------------------------------------- report


def render_tree(root, depth, counts, per_dir=10):
    lines = []

    def rec(d, prefix, level):
        try:
            entries = sorted(os.scandir(d), key=lambda e: (not e.is_dir(), e.name.lower()))
        except OSError:
            return
        dirs = [e for e in entries if e.is_dir() and keep_dir(Path(e.path))]
        fl = [e for e in entries if e.is_file()]
        for e in dirs:
            lines.append(f"{prefix}{e.name}/  ({counts.get(Path(e.path), 0)} files)")
            if level < depth:
                rec(Path(e.path), prefix + "  ", level + 1)
        for e in fl[:per_dir]:
            lines.append(f"{prefix}{e.name}")
        if len(fl) > per_dir:
            lines.append(f"{prefix}... +{len(fl) - per_dir} more files")

    rec(root, "", 1)
    return lines


def build_report(root, args):
    def cap(lines, n=None):
        n = n or args.max_lines
        return lines[:n] + ([f"... +{len(lines) - n} more"] if len(lines) > n else [])

    files = collect_files(root)
    rel = {p: p.relative_to(root).as_posix() for p in files}
    counts = Counter()
    for p in files:
        for a in list(p.relative_to(root).parents)[:-1]:
            counts[root / a] += 1

    texts, big, env_files = {}, [], []
    for p in files:
        r, name, ext = rel[p], p.name.lower(), p.suffix.lower()
        if is_secret_env_file(name):
            env_files.append(r)
            continue
        wanted = (
            ext in LANG or name in CONFIG_NAMES or name.startswith("requirements")
            or ext in {".md", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".tf"}
        )
        if ext == ".json" and (name in {"package.json", "tsconfig.json", "composer.json"} or size_of(p) < 200_000):
            wanted = True
        if not wanted:
            continue
        limit = 8_000_000 if ext == ".ipynb" else 1_500_000
        t = load_text(p, limit)
        if t is None:
            big.append(r)
        else:
            texts[r] = t

    code = [p for p in files if p.suffix.lower() in LANG and p.suffix.lower() != ".ipynb"]
    notebooks = [p for p in files if p.suffix.lower() == ".ipynb"]
    docs = [
        p for p in files
        if p.suffix.lower() in DOC_EXT and p.name.lower() not in CONFIG_NAMES and not p.name.lower().startswith("requirements")
    ]

    def is_data(p):
        ext, name = p.suffix.lower(), p.name.lower()
        if ext not in DATA_EXT:
            return False
        if ext == ".json" and (name.startswith(("package", "tsconfig", "composer")) or size_of(p) < 50_000):
            return False
        return True

    data = [p for p in files if is_data(p)]

    langs = defaultdict(lambda: [0, 0])
    lines_of = {}
    for p in code:
        L = LANG[p.suffix.lower()]
        langs[L][0] += 1
        t = texts.get(rel[p])
        if t is not None:
            n = t.count("\n") + 1
            langs[L][1] += n
            lines_of[rel[p]] = n

    # ---- python analysis
    py = [p for p in code if p.suffix.lower() == ".py" and rel[p] in texts]
    trees, parse_fail = {}, []
    for p in py:
        try:
            trees[rel[p]] = ast.parse(texts[rel[p]])
        except Exception as e:
            ln = getattr(e, "lineno", None)
            parse_fail.append(f"{rel[p]} (line {ln})" if ln else f"{rel[p]} (not valid Python)")

    local_map = {}
    for r in trees:
        parts = r[:-3].split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            local_map[".".join(parts)] = r
    suffix_count, suffix_map = Counter(), {}
    for dotted, r in local_map.items():
        segs = dotted.split(".")
        for i in range(len(segs)):
            s = ".".join(segs[i:])
            suffix_count[s] += 1
            suffix_map.setdefault(s, r)

    def lookup(c):
        if not c:
            return None
        if c in local_map:
            return local_map[c]
        if suffix_count.get(c) == 1:
            return suffix_map[c]
        return None

    routes, models, outline = [], [], {}
    local_deps = defaultdict(set)
    libs = Counter()
    for r, tree in trees.items():
        text = texts[r]
        routes += py_routes(tree, r)
        if "urlpatterns" in text:
            routes += django_routes(tree, r)
        models += py_models(tree, r)
        outline[r] = py_outline(tree)
        pkg = r[:-3].split("/")[:-1]
        ext_libs = set()
        for mod, level, names in py_imports(tree):
            hits = {lookup(c) for c in import_candidates(mod, level, names, pkg)}
            hits.discard(None)
            hits.discard(r)
            if hits:
                local_deps[r] |= hits
            elif not level and mod:
                top = mod.split(".")[0]
                if top not in STDLIB:
                    ext_libs.add(top)
        libs.update(ext_libs)

    # ---- js analysis
    js = [p for p in code if p.suffix.lower() in JS_EXT and rel[p] in texts]
    js_known = {rel[p] for p in js}
    for p in js:
        r, text = rel[p], texts[rel[p]]
        for m in JS_ROUTE.finditer(text):
            routes.append((m.group(1).upper(), m.group(3), "", f"{r}:{line_of(text, m.start())}"))
        ext_libs = set()
        for spec in JS_IMPORT.findall(text):
            if spec.startswith("."):
                t = resolve_js(spec, r, js_known)
                if t and t != r:
                    local_deps[r].add(t)
            else:
                name = js_pkg_name(spec)
                if name:
                    ext_libs.add(name)
        libs.update(ext_libs)
        syms = []
        for m in JS_SYMS.finditer(text):
            name = m.group(1) or m.group(2) or m.group(3)
            kind = "class" if m.group(2) else "function"
            syms.append(f"{kind} {name} L{line_of(text, m.start())}")
        outline[r] = ("", syms)
    for r, t in texts.items():
        if r.endswith(".java"):
            for m in JAVA_ROUTE.finditer(t):
                routes.append((m.group(1).upper(), m.group(2), "", f"{r}:{line_of(t, m.start())}"))

    # ---- notebooks
    nb_lines = []
    for p in notebooks:
        r = rel[p]
        info = notebook_info(texts[r]) if r in texts else None
        if info is None:
            nb_lines.append(f"{r}: too large or not parseable")
            continue
        n_code, n_md, has_out, heads, nb_libs = info
        nb_lines.append(
            f"{r}: {n_code} code cells, {n_md} markdown cells, saved outputs: {'yes' if has_out else 'no'}"
        )
        for h in heads:
            nb_lines.append(f"    {h}")
        for lib in nb_libs:
            if lib not in STDLIB:
                libs[lib] += 1

    # ---- entry points
    entries = {}
    for p in code:
        if p.name.lower() in ENTRY_NAMES:
            entries[rel[p]] = "conventional entry file name"
    for r, t in texts.items():
        if r.endswith(".py"):
            if re.search(r"""if\s+__name__\s*==\s*['"]__main__['"]""", t):
                entries.setdefault(r, "has a __main__ guard")
            if re.search(r"^\s*(?:import|from)\s+streamlit\b", t, re.M):
                entries[r] = "Streamlit app (run with streamlit run)"

    # ---- config
    cfg = []
    for p in files:
        r, name = rel[p], p.name.lower()
        if (
            name in CONFIG_NAMES or name.startswith("requirements") or name.endswith(".tf")
            or r.startswith(".github/workflows/")
        ):
            cfg.append(r)
    cfg_detail = []
    for r in cfg:
        t = texts.get(r)
        name = posixpath.basename(r).lower()
        if t is None:
            continue
        if name.startswith("requirements") and name.endswith(".txt"):
            cfg_detail.append(f"{r}: " + ", ".join(parse_requirements(t)[:40]))
        elif name == "pyproject.toml":
            deps = parse_pyproject(t)
            if deps:
                cfg_detail.append(f"{r}: " + ", ".join(deps[:40]))
        elif name == "package.json":
            try:
                d = json.loads(t)
                cfg_detail.append(f"{r} dependencies: " + ", ".join(list(d.get("dependencies", {}))[:40]))
                if d.get("devDependencies"):
                    cfg_detail.append(f"{r} devDependencies: " + ", ".join(list(d["devDependencies"])[:25]))
                for k, v in list(d.get("scripts", {}).items())[:10]:
                    cfg_detail.append(f"{r} script {k}: {v}")
                if d.get("main"):
                    entries.setdefault(d["main"], "package.json main")
            except ValueError:
                pass
        elif name == "dockerfile":
            froms = re.findall(r"(?im)^FROM\s+(\S+)", t)
            cfg_detail.append(f"{r}: base image {', '.join(froms)}" if froms else r)
        elif name.startswith("docker-compose"):
            svc = []
            m = re.search(r"(?m)^services:\s*$", t)
            if m:
                for line in t[m.end():].splitlines():
                    if line and not line.startswith((" ", "\t", "#")):
                        break
                    s = re.match(r"^  ([A-Za-z0-9_.\-]+):\s*$", line)
                    if s:
                        svc.append(s.group(1))
            cfg_detail.append(f"{r}: services {', '.join(svc)}" if svc else r)
        elif name == ".env.example":
            keys = re.findall(r"(?m)^\s*([A-Z][A-Z0-9_]*)\s*=", t)
            cfg_detail.append(f"{r}: keys {', '.join(keys)}" if keys else r)
    if any(rel[p].endswith("dbt_project.yml") for p in files):
        n_models = sum(1 for r in rel.values() if "/models/" in "/" + r and r.endswith(".sql"))
        cfg_detail.append(f"dbt project detected: {n_models} .sql files under models/")
    dags = [r for r, t in texts.items() if r.endswith(".py") and re.search(r"\bDAG\s*\(|@dag\b", t)]
    if dags:
        cfg_detail.append("Airflow DAG files: " + ", ".join(dags[:8]))

    # ---- env vars, secrets, SQL tables
    env_vars = defaultdict(set)
    secrets, sql_tables = [], []
    for r, t in texts.items():
        if r.endswith(".md") or posixpath.basename(r).endswith(".lock") or "package-lock" in r:
            continue
        for pat in ENV_PATTERNS:
            for m in pat.finditer(t):
                env_vars[m.group(1)].add(r)
        for m in SQL_TABLE.finditer(t):
            sql_tables.append(f"{m.group(1)}  ({r}:{line_of(t, m.start())})")
        seen = set()
        for i, line in enumerate(t.splitlines(), 1):
            if len(line) > 400:
                continue
            m = SECRET_NAME.search(line)
            if m and not PLACEHOLDER.search(m.group(3)) and i not in seen:
                seen.add(i)
                tag = " (test file)" if is_test_file(r) else ""
                secrets.append(f"{r}:{i}  variable `{m.group(1)}`{tag}")
            elif SECRET_VALUE.search(line) and i not in seen:
                seen.add(i)
                secrets.append(f"{r}:{i}  key-shaped value")
    if ".env.example" in {posixpath.basename(r) for r in cfg}:
        for r in cfg:
            if posixpath.basename(r) == ".env.example" and r in texts:
                for k in re.findall(r"(?m)^\s*([A-Z][A-Z0-9_]*)\s*=", texts[r]):
                    env_vars[k].add(r)

    # ---- tests
    tests = []
    for p in files:
        r = rel[p]
        if p.suffix.lower() not in {".py"} | JS_EXT or not is_test_file(r) or r not in texts:
            continue
        t = texts[r]
        if r in trees:
            names = [
                n.name for n in ast.walk(trees[r])
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test")
            ]
        else:
            names = [m.group(1) for m in re.finditer(r"""\b(?:it|test)\(\s*['"`]([^'"`]+)['"`]""", t)]
        mock = "mocking: yes" if MOCK_SIGNS.search(t) else "mocking: no"
        shown = ", ".join(names[:6]) + (", ..." if len(names) > 6 else "")
        tests.append(f"{r}: {len(names)} tests ({mock}){'  ' + shown if names else ''}")

    # ---- ranking and graph
    fan_in = Counter(d for ds in local_deps.values() for d in ds)
    ranked = [r for r in outline if not is_test_file(r)]
    ranked.sort(key=lambda r: (r in entries, fan_in[r], lines_of.get(r, 0)), reverse=True)

    out = []
    w = out.append
    w(f"# Project inventory: {root.name}")
    w("")
    w(f"Scanned {len(files)} files: {len(code)} code, {len(notebooks)} notebooks, {len(docs)} documents, {len(data)} data files.")
    w("This is a heuristic map. Open files before teaching from it.")
    w("")

    w("## Languages")
    for L, (n, ln) in sorted(langs.items(), key=lambda kv: -kv[1][1]):
        w(f"- {L}: {n} files, {ln} lines")
    w("")

    w(f"## File tree (depth {args.depth})")
    w("```")
    out += cap(render_tree(root, args.depth, counts), max(args.max_lines * 2, 80))
    w("```")
    w("")

    w("## Documents")
    readmes = [rel[p] for p in docs if p.name.lower().startswith("readme")]
    w(f"README present: {'yes (' + ', '.join(readmes) + ')' if readmes else 'no'}")
    doc_lines = []
    for p in docs:
        r = rel[p]
        head = ""
        if r in texts and r.endswith(".md"):
            head = next((ln.strip() for ln in texts[r].splitlines() if ln.startswith("#")), "")
        doc_lines.append(f"- {r}" + (f": {head}" if head else ""))
    out += cap(doc_lines)
    if any(p.suffix.lower() in {".pdf", ".pptx", ".docx"} for p in docs):
        w("(PDF, PPTX and DOCX files need the pdf-reading, pptx or docx skill to read.)")
    w("")

    w("## Config, dependencies and infrastructure")
    if env_files:
        w(f"Env files present and deliberately not read: {', '.join(env_files)}")
    out += cap([f"- {c}" for c in cfg_detail] or [f"- {c}" for c in cfg] or ["- none found"])
    w("")

    w("## Entry points")
    out += cap([f"- {r}: {why}" for r, why in sorted(entries.items())] or ["- none detected"])
    w("")

    w("## Third-party libraries imported (files importing each)")
    out += cap([f"- {name}: {n}" for name, n in libs.most_common(30)] or ["- none detected"], 30)
    w("")

    w("## HTTP routes")
    def route_key(x):
        f, _, n = x[3].rpartition(":")
        return (f, int(n) if n.isdigit() else 0)

    seen_routes = sorted(set(routes), key=route_key)
    out += cap([f"- {m} {path} → {fn}  ({where})" if fn else f"- {m} {path}  ({where})"
                for m, path, fn, where in seen_routes] or ["- none detected"])
    w("")

    w("## Data models and tables")
    mlines = [f"- {n}({', '.join(b)}): {', '.join(f) or 'no simple fields found'}  ({where})" for n, b, f, where in models]
    mlines += [f"- table {t}" for t in sql_tables]
    out += cap(mlines or ["- none detected"])
    w("")

    w("## Code outline (entry points and most-imported files first)")
    for r in ranked[: args.max_files]:
        doc, items = outline[r]
        tag = " [entry point]" if r in entries else ""
        w(f"### {r} ({lines_of.get(r, '?')} lines){tag}, imported by {fan_in[r]} file(s)")
        if doc:
            w(f"Docstring: {doc}")
        w("```")
        out += cap(items or ["(no top-level functions or classes found)"], 18)
        w("```")
    if len(ranked) > args.max_files:
        w(f"... +{len(ranked) - args.max_files} more files not outlined (raise --max-files)")
    w("")

    w("## Local import graph")
    graph = [
        f"- {r} → {', '.join(sorted(local_deps[r]))}"
        for r in sorted(local_deps, key=lambda r: (-fan_in[r], r)) if local_deps[r] and not is_test_file(r)
    ]
    out += cap(graph or ["- none detected"])
    top = [f"{r} ({n})" for r, n in fan_in.most_common(8) if n > 1]
    if top:
        w("Most imported: " + ", ".join(top))
    w("")

    w("## Environment variables referenced (names only)")
    out += cap([f"- {k}: {', '.join(sorted(v)[:3])}" for k, v in sorted(env_vars.items())] or ["- none detected"])
    w("")

    w("## Possible hard-coded secrets (candidates, values never printed)")
    out += cap([f"- {s}" for s in secrets] or ["- none detected"])
    w("")

    w("## Tests")
    out += cap([f"- {t}" for t in tests] or ["- no test files detected"])
    w("")

    w("## Notebooks")
    out += cap(nb_lines or ["none"])
    w("")

    w("## Data files")
    dl = []
    for p in data:
        size = size_of(p)
        line = f"- {rel[p]} ({size / 1024:.0f} KB)"
        if p.suffix.lower() in {".csv", ".tsv"} and len(dl) < 10:
            line += f"  header: {first_line(p)}"
        dl.append(line)
    out += cap(dl or ["- none"])
    w("")

    notes = []
    if parse_fail:
        notes.append("Python files that did not parse (Python 2 or syntax errors): " + ", ".join(parse_fail[:10]))
    if big:
        notes.append("Skipped (too large or unreadable): " + ", ".join(big[:10]))
    if len(files) >= 20000:
        notes.append("File scan stopped at 20000 files.")
    if notes:
        w("## Notes")
        for n in notes:
            w(f"- {n}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Print a Markdown map of a project folder or archive.")
    ap.add_argument("path")
    ap.add_argument("--depth", type=int, default=3, help="tree depth (default 3)")
    ap.add_argument("--max-files", type=int, default=25, help="files to outline (default 25)")
    ap.add_argument("--max-lines", type=int, default=40, help="max lines per section (default 40)")
    ap.add_argument("--out", help="write the report to this file instead of stdout")
    args = ap.parse_args()

    src = Path(args.path).expanduser()
    if not src.exists():
        sys.exit(f"Path not found: {src}")
    root = src if src.is_dir() else extract_archive(src)
    report = build_report(root.resolve(), args)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"Wrote {args.out} ({report.count(chr(10)) + 1} lines)")
    else:
        try:
            print(report)
            sys.stdout.flush()
        except BrokenPipeError:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""API↔Frontend Drift Guard (lente L4: cableado api.ts ↔ urls.py).

Confronta las rutas registradas en el backend (config/urls.py + urls.py de cada
app, incluyendo routers DRF con sus @actions) contra los endpoints que el
frontend llama por literal en `frontend/src/**/*.{ts,vue}` (api.get/post/...).

Dos direcciones:
- ROTO (dirección A): el frontend llama una ruta que NO existe en el backend.
  FALLA SIEMPRE — no hay baseline que valga para cableado roto.
- HUÉRFANO (dirección B): una ruta de los KERNELS (apps.kernels.*) sin ningún
  caller en el frontend. FALLA solo si no está en el baseline
  (qa/contracts/api_frontend_drift_baseline.json) con su razón explícita.

La dirección B se limita a los kernels a propósito: son la capa cuyo cableado
se audita (lente L4); los módulos verticales tienen huecos intencionales de
sobra y meterían ruido. La dirección A sí valida contra TODAS las rutas.

Diseño: scan estático puro (sin runtime Django ni node), estilo ratchet con
baseline — igual que route_authz_guard.py. El baseline es un trinquete: solo
se encoge; una entrada nueva exige razón explícita en el PR.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
from datetime import datetime, timezone
from pathlib import Path

# Métodos axios que nos interesan. Soporta genéricos TS con objetos:
# api.post<{ ok: boolean; id: string }>(`/ruta/${x}/`, ...).
FRONT_CALL_RE = re.compile(
    r"\b(?:api|authApi)\s*\.\s*(?:get|post|put|patch|delete)\s*(?:<[^()]*?>)?\s*\(\s*([`'\"])(.*?)\1",
    re.DOTALL,
)
# Cualquier literal con pinta de ruta API ('/x/y/...') — evidencia LAXA de consumo
# para la dirección B (cubre URLs armadas en una variable antes del api.post(url)).
FRONT_PATH_LITERAL_RE = re.compile(r"([`'\"])(/[A-Za-z0-9_\-]+/[^`'\"]*?)\1")
# Constantes locales tipo `const BASE = '/nomina/biometric';` → se sustituyen en
# los templates `${BASE}/devices/` antes de normalizar.
FRONT_CONST_RE = re.compile(r"\bconst\s+(\w+)\s*=\s*([`'\"])(/[A-Za-z0-9_\-/]*)\2")
# Segmento de parámetro Django (<int:x>, <uuid:x>, <x>) o grupo regex (?P<x>...).
DJANGO_PARAM_RE = re.compile(r"<[^>]+>")
REGEX_GROUP_RE = re.compile(r"\(\?P<[^>]+>[^)]*\)")
TEMPLATE_PARAM_RE = re.compile(r"\$\{[^}]*\}")


def _canonical(route: str) -> str:
    """Normaliza una ruta a su clave canónica: sin prefijo api(/v1), params → <p>."""
    r = route.split("?")[0].strip()
    r = TEMPLATE_PARAM_RE.sub("<p>", r)
    r = REGEX_GROUP_RE.sub("<p>", r)
    r = DJANGO_PARAM_RE.sub("<p>", r)
    r = r.strip("/")
    for prefix in ("api/v1/", "api/"):
        if r == prefix.strip("/"):
            r = ""
            break
        if r.startswith(prefix):
            r = r[len(prefix):]
            break
    # re_path deja anclas/regex sueltos; limpia lo más común.
    r = r.replace("^", "").replace("$", "")
    return r.strip("/")


# ---------------------------------------------------------------------------
# Backend: recolección de rutas
# ---------------------------------------------------------------------------

def _str_const(node) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _include_target(call: ast.Call):
    """De un include(...) devuelve ('module', str) | ('var', str) | None."""
    if not (isinstance(call.func, ast.Name) and call.func.id == "include"):
        return None
    if not call.args:
        return None
    arg = call.args[0]
    s = _str_const(arg)
    if s is not None:
        return ("module", s)
    # include((urls, "ns")) o include(("module", "ns"))
    if isinstance(arg, ast.Tuple) and arg.elts:
        s = _str_const(arg.elts[0])
        if s is not None:
            return ("module", s)
    # include(router.urls) → ('var', 'router')
    if isinstance(arg, ast.Attribute) and arg.attr == "urls" and isinstance(arg.value, ast.Name):
        return ("var", arg.value.id)
    # include(api_v1_urlpatterns)
    if isinstance(arg, ast.Name):
        return ("var", arg.id)
    return None


def _path_entries(list_node: ast.List):
    """Extrae (route, kind, payload) de una lista de path()/re_path()."""
    out = []
    for elt in list_node.elts:
        if not isinstance(elt, ast.Call):
            continue
        fname = elt.func.id if isinstance(elt.func, ast.Name) else (
            elt.func.attr if isinstance(elt.func, ast.Attribute) else ""
        )
        if fname not in {"path", "re_path"}:
            continue
        if not elt.args:
            continue
        route = _str_const(elt.args[0])
        if route is None:
            continue
        target = _include_target(elt.args[1]) if len(elt.args) > 1 and isinstance(elt.args[1], ast.Call) else None
        if target is not None:
            out.append((route, target[0], target[1]))
        else:
            out.append((route, "view", None))
    return out


def _viewset_actions(app_dir: Path) -> dict[str, list[tuple[str, bool]]]:
    """Mapa clase → [(url_path, detail)] de métodos @action en views*.py del app."""
    actions: dict[str, list[tuple[str, bool]]] = {}
    for vf in sorted(app_dir.glob("views*.py")):
        try:
            tree = ast.parse(vf.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for dec in stmt.decorator_list:
                    if not isinstance(dec, ast.Call):
                        continue
                    dname = dec.func.id if isinstance(dec.func, ast.Name) else (
                        dec.func.attr if isinstance(dec.func, ast.Attribute) else ""
                    )
                    if dname != "action":
                        continue
                    detail = False
                    url_path = stmt.name.replace("_", "-")
                    for kw in dec.keywords:
                        if kw.arg == "detail" and isinstance(kw.value, ast.Constant):
                            detail = bool(kw.value.value)
                        if kw.arg == "url_path":
                            s = _str_const(kw.value)
                            if s:
                                url_path = s
                    actions.setdefault(node.name, []).append((url_path, detail))
    return actions


def _router_registrations(tree: ast.Module) -> dict[str, list[tuple[str, str]]]:
    """Mapa var_router → [(prefix, clase)] de las llamadas router.register(...)."""
    regs: dict[str, list[tuple[str, str]]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "register"):
            continue
        if not isinstance(node.func.value, ast.Name):
            continue
        if not node.args:
            continue
        prefix = _str_const(node.args[0])
        if prefix is None:
            continue
        cls = ""
        if len(node.args) > 1:
            a = node.args[1]
            cls = a.attr if isinstance(a, ast.Attribute) else (a.id if isinstance(a, ast.Name) else "")
        regs.setdefault(node.func.value.id, []).append((prefix, cls))
    return regs


def _module_to_path(module: str, src_root: Path) -> Path | None:
    p = src_root / (module.replace(".", "/") + ".py")
    return p if p.exists() else None


def _assigned_lists(tree: ast.Module) -> dict[str, list[ast.List]]:
    """Listas por nombre, cubriendo Assign, AnnAssign (x: list = [...]) y AugAssign (x += [...])."""
    lists: dict[str, list[ast.List]] = {}
    for node in ast.walk(tree):
        name, value = None, None
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.List):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    name, value = tgt.id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.List):
            if isinstance(node.target, ast.Name):
                name, value = node.target.id, node.value
        elif isinstance(node, ast.AugAssign) and isinstance(node.value, ast.List):
            if isinstance(node.target, ast.Name):
                name, value = node.target.id, node.value
        if name is not None and value is not None:
            lists.setdefault(name, []).append(value)
    return lists


def _collect_app_routes(urls_path: Path, prefix: str, src_root: Path, seen: set[Path]):
    """Rutas (full_route, urls_file) de un urls.py de app, expandiendo routers e includes."""
    if urls_path in seen:
        return []
    seen.add(urls_path)
    try:
        tree = ast.parse(urls_path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []

    routes: list[tuple[str, Path]] = []
    routers = _router_registrations(tree)
    actions = _viewset_actions(urls_path.parent) if routers else {}

    for list_nodes in _assigned_lists(tree).values():
        for list_node in list_nodes:
            for route, kind, payload in _path_entries(list_node):
                full = prefix + route
                if kind == "view":
                    routes.append((full, urls_path))
                elif kind == "module":
                    sub = _module_to_path(payload, src_root)
                    if sub is not None:
                        routes.extend(_collect_app_routes(sub, full, src_root, seen))
                elif kind == "var" and payload in routers:
                    for reg_prefix, cls in routers[payload]:
                        base = f"{full}{reg_prefix}/"
                        routes.append((base, urls_path))
                        routes.append((base + "<pk>/", urls_path))
                        for url_path, detail in actions.get(cls, []):
                            if detail:
                                routes.append((base + f"<pk>/{url_path}/", urls_path))
                            else:
                                routes.append((base + f"{url_path}/", urls_path))
    return routes


def collect_backend_routes(root: Path):
    """Devuelve (all_routes, kernel_routes): dicts canónico → info."""
    src_root = root / "backend" / "src"
    config_urls = src_root / "config" / "urls.py"
    tree = ast.parse(config_urls.read_text(encoding="utf-8"))

    # Listas module-level (api_v1_urlpatterns, urlpatterns con sus +=, ...)
    lists = _assigned_lists(tree)

    all_routes: dict[str, dict] = {}
    kernel_routes: dict[str, dict] = {}

    def add(full_route: str, module: str):
        canon = _canonical(full_route)
        if not canon or canon.startswith(("admin", "schema", "csp/report")):
            return
        info = {"route": "/" + canon + "/", "module": module}
        all_routes.setdefault(canon, info)
        if module.startswith("apps.kernels."):
            kernel_routes.setdefault(canon, info)

    def walk_lists(nodes: list[ast.List], prefix: str, seen_vars: set[str]):
        for lst in nodes:
            for route, kind, payload in _path_entries(lst):
                full = prefix + route
                if kind == "view":
                    add(full, "config")
                elif kind == "module":
                    sub = _module_to_path(payload, src_root)
                    if sub is None:
                        continue
                    for r, _f in _collect_app_routes(sub, full, src_root, set()):
                        add(r, payload)
                elif kind == "var" and payload in lists and payload not in seen_vars:
                    walk_lists(lists[payload], full, seen_vars | {payload})

    if "urlpatterns" in lists:
        walk_lists(lists["urlpatterns"], "", set())
    return all_routes, kernel_routes


# ---------------------------------------------------------------------------
# Frontend: recolección de llamadas
# ---------------------------------------------------------------------------

def _is_dynamic(canon: str) -> bool:
    """Quedó un template sin resolver (anidado/roto) → no verificable estático."""
    return "$" in canon or "{" in canon


def collect_frontend_calls(root: Path):
    """(strict, loose, dynamic): llamadas api.<verbo>(literal), evidencia laxa
    de consumo (cualquier literal-ruta), y llamadas dinámicas no verificables."""
    front_src = root / "frontend" / "src"
    strict: dict[str, set[str]] = {}
    loose: set[str] = set()
    dynamic: list[dict] = []
    for path in sorted(front_src.rglob("*")):
        if path.suffix not in {".ts", ".vue"} or not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        consts = {m.group(1): m.group(3) for m in FRONT_CONST_RE.finditer(text)}

        def resolve_consts(url: str) -> str:
            for name, value in consts.items():
                url = url.replace("${" + name + "}", value)
            return url

        for m in FRONT_CALL_RE.finditer(text):
            url = resolve_consts(m.group(2).strip())
            if not url or not url.startswith("/"):
                continue
            canon = _canonical(url)
            if not canon:
                continue
            if _is_dynamic(canon):
                dynamic.append({"call": url, "file": rel})
                continue
            strict.setdefault(canon, set()).add(rel)
        for m in FRONT_PATH_LITERAL_RE.finditer(text):
            canon = _canonical(resolve_consts(m.group(2).strip()))
            if canon and not _is_dynamic(canon):
                loose.add(canon)
    return strict, loose, dynamic


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------

def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="Drift api.ts ↔ urls.py (lente L4, ratchet baseline).")
    p.add_argument("--root", default=".")
    p.add_argument("--baseline", default="qa/contracts/api_frontend_drift_baseline.json")
    p.add_argument("--output", default="qa/reports/api_frontend_drift_report.json")
    p.add_argument("--write-baseline", action="store_true",
                   help="Regenera el baseline con los huérfanos actuales preservando razones existentes; "
                        "los nuevos quedan 'TODO: justificar'. Solo para bootstrap/mantenimiento REVISADO.")
    p.add_argument("--report-only", action="store_true", help="Imprime hallazgos y sale 0 (modo CI informativo).")
    args = p.parse_args()

    root = Path(args.root).resolve()
    all_routes, kernel_routes = collect_backend_routes(root)
    front_calls, front_loose, front_dynamic = collect_frontend_calls(root)

    def segments_match(backend: str, front: str) -> bool:
        """Match por segmentos: <p> es comodín en ambos lados (un ${x} del frontend
        puede ser un id O un segmento de acción elegido dinámicamente)."""
        bs, fs = backend.split("/"), front.split("/")
        if len(bs) != len(fs):
            return False
        return all(b == f or b == "<p>" or f == "<p>" for b, f in zip(bs, fs))

    backend_canons = list(all_routes)

    def call_resolves(canon: str) -> bool:
        if canon in all_routes:
            return True
        return any(segments_match(b, canon) for b in backend_canons)

    consumption_evidence = set(front_calls) | front_loose

    def route_consumed(canon: str) -> bool:
        if canon in consumption_evidence:
            return True
        return any(segments_match(canon, f) for f in consumption_evidence)

    # Dirección A: frontend → ruta inexistente (contra TODAS las rutas backend).
    # Solo llamadas con literal estático completo; las dinámicas se reportan aparte.
    broken = [
        {"call": "/" + canon + "/", "files": sorted(files)}
        for canon, files in sorted(front_calls.items())
        if not call_resolves(canon)
    ]

    # Dirección B: ruta kernel sin caller frontend (evidencia estricta o laxa).
    orphans = {
        canon: info for canon, info in sorted(kernel_routes.items())
        if not route_consumed(canon)
    }

    baseline_path = (root / args.baseline).resolve()
    baseline: dict = {}
    if baseline_path.exists():
        baseline = json.loads(baseline_path.read_text(encoding="utf-8")).get("orphans", {})

    if args.write_baseline:
        merged = {}
        for canon, info in orphans.items():
            prev = baseline.get(canon, {})
            merged[canon] = {
                "route": info["route"],
                "module": info["module"],
                "reason": prev.get("reason", "TODO: justificar"),
                "planned_wave": prev.get("planned_wave"),
            }
        payload = {
            "version": 1,
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "orphans": merged,
            "notes": [
                "Baseline-trinquete de rutas KERNEL sin consumo en el frontend (dirección B de la lente L4).",
                "Cada entrada exige razón explícita y, si aplica, la oleada donde se cierra (planned_wave).",
                "El cableado ROTO (frontend → ruta inexistente) NUNCA se baselinea: se arregla.",
            ],
        }
        _write_json(baseline_path, payload)
        print(f"[qa] baseline L4 escrito: {len(merged)} huérfano(s) en {args.baseline}")
        return 0

    unbaselined = {c: i for c, i in orphans.items() if c not in baseline}
    stale = sorted(c for c in baseline if c not in orphans)

    status = "passed" if not broken and not unbaselined else "failed"
    report = {
        "status": status,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "summary": {
            "backend_routes_total": len(all_routes),
            "kernel_routes_total": len(kernel_routes),
            "frontend_calls_total": len(front_calls),
            "dynamic_calls_skipped": len(front_dynamic),
            "broken_calls": len(broken),
            "kernel_orphans_total": len(orphans),
            "orphans_baselined": len(orphans) - len(unbaselined),
            "orphans_unbaselined": len(unbaselined),
            "stale_baseline_entries": len(stale),
        },
        "broken": broken,
        "dynamic_calls_skipped": front_dynamic,
        "orphans_unbaselined": [
            {"route": i["route"], "module": i["module"]} for i in unbaselined.values()
        ],
        "stale_baseline": stale,
    }
    _write_json((root / args.output).resolve(), report)

    if stale:
        print(f"[qa] L4 drift: {len(stale)} entrada(s) de baseline ya cableadas o removidas (limpia el baseline):")
        for c in stale:
            print(f"[qa]   stale: {c}")
    if broken:
        print("[qa] L4 drift: CABLEADO ROTO (frontend llama rutas inexistentes):")
        for b in broken:
            print(f"[qa]   {b['call']} <- {', '.join(b['files'])}")
    if unbaselined:
        print("[qa] L4 drift: huérfanos kernel SIN baseline (añade UI o justifica en el baseline):")
        for i in unbaselined.values():
            print(f"[qa]   {i['route']} ({i['module']})")

    if args.report_only:
        print(f"[qa] L4 drift report-only: status={status} "
              f"(rotos: {len(broken)}, huérfanos sin baseline: {len(unbaselined)})")
        return 0

    if status == "failed":
        print("[qa] api frontend drift guard failed")
        return 1
    print(f"[qa] api frontend drift guard passed "
          f"(rutas: {len(all_routes)}, llamadas front: {len(front_calls)}, "
          f"huérfanos kernel baselineados: {len(orphans)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

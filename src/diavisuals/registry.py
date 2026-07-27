from __future__ import annotations

import csv
import base64
import hashlib
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
from typing import Any


DEFAULT_RELEASE = "v0.1.2"
DEFAULT_COMPATIBILITY = "mermaid-11.4.2-plantuml-1.2026.1"
DEFAULT_FAMILY = "benizar"
DEFAULT_REMOTE = "git@github.com:dosquartsdedocs/diavisuals.git"
HEX_COLOR_RE = re.compile(r"#[0-9A-Fa-f]{6}\b")
MERMAID_TEXT_STARTS = {
    "architecture-beta",
    "block",
    "classdiagram",
    "erdiagram",
    "flowchart",
    "gantt",
    "gitgraph",
    "graph",
    "journey",
    "kanban",
    "mindmap",
    "packet-beta",
    "pie",
    "quadrantchart",
    "requirementdiagram",
    "sankey-beta",
    "sequencediagram",
    "statediagram",
    "statediagram-v2",
    "timeline",
    "treemap-beta",
    "xychart-beta",
}
OUTPUT_MIME_TYPES = {
    "svg": "image/svg+xml",
    "png": "image/png",
    "pdf": "application/pdf",
}


def repo_dir() -> pathlib.Path:
    env = os.environ.get("DIAVISUALS_DIR", "").strip()
    if env:
        return pathlib.Path(env).expanduser().resolve()

    module_path = pathlib.Path(__file__).resolve()
    checkout = module_path.parents[2]
    if (checkout / "styles").is_dir() and (checkout / "compat").is_dir():
        return checkout

    packaged = module_path.parent / "assets"
    if packaged.is_dir():
        return packaged

    return checkout


def rel(path: pathlib.Path, root: pathlib.Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def run(command: list[str], cwd: pathlib.Path | None = None, timeout: int = 120) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=str(cwd or repo_dir()),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def git_head(path: pathlib.Path | None = None) -> str | None:
    root = path or repo_dir()
    result = run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], cwd=root)
    if result["returncode"] == 0:
        return str(result["stdout"]).strip()
    return None


def git_tag(path: pathlib.Path | None = None) -> str | None:
    root = path or repo_dir()
    result = run(["git", "-C", str(root), "describe", "--tags", "--exact-match"], cwd=root)
    if result["returncode"] == 0:
        return str(result["stdout"]).strip()
    return None


def parse_env(path: pathlib.Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def renderer_profile(profile: str = DEFAULT_COMPATIBILITY) -> dict[str, Any]:
    compat = compatibility_status(profile)
    values = compat.get("values", {}) if isinstance(compat.get("values"), dict) else {}
    image = str(values.get("DIAVISUALS_RENDER_IMAGE") or "").strip()
    dockerfile = str(values.get("DIAVISUALS_RENDER_DOCKERFILE") or "").strip()
    issues: list[str] = []
    if not compat.get("ok"):
        issues.append(f"missing compatibility profile: {profile}")
    if not image:
        issues.append("compatibility profile does not define DIAVISUALS_RENDER_IMAGE")
    if not dockerfile:
        issues.append("compatibility profile does not define DIAVISUALS_RENDER_DOCKERFILE")

    dockerfile_path = repo_dir() / dockerfile if dockerfile else None
    if dockerfile_path is not None and not dockerfile_path.is_file():
        issues.append(f"renderer Dockerfile not found: {dockerfile}")

    return {
        "ok": not issues,
        "profile": str(compat.get("requested") or pathlib.Path(profile).stem),
        "image": image,
        "dockerfile": dockerfile,
        "dockerfile_path": str(dockerfile_path) if dockerfile_path else None,
        "values": values,
        "issues": issues,
    }


def build_renderer_image(profile: str = DEFAULT_COMPATIBILITY, *, dry_run: bool = False) -> dict[str, Any]:
    root = repo_dir()
    renderer = renderer_profile(profile)
    if not renderer["ok"]:
        return {"ok": False, "renderer": renderer}

    values = renderer["values"]
    command = [
        "docker",
        "build",
        "-f",
        renderer["dockerfile"],
        "--build-arg",
        f"MERMAID_CLI_VERSION={values.get('MERMAID_CLI_VERSION', '')}",
        "--build-arg",
        f"PLANTUML_VERSION={values.get('PLANTUML_VERSION', '')}",
        "-t",
        renderer["image"],
        ".",
    ]
    if dry_run:
        return {"ok": True, "dry_run": True, "renderer": renderer, "command": command}
    result = run(command, cwd=root, timeout=1800)
    return {"ok": result["returncode"] == 0, "renderer": renderer, "result": result}


def ensure_renderer_image(profile: str = DEFAULT_COMPATIBILITY) -> dict[str, Any]:
    renderer = renderer_profile(profile)
    if not renderer["ok"]:
        return {"ok": False, "renderer": renderer}
    inspect = run(["docker", "image", "inspect", renderer["image"]], cwd=repo_dir(), timeout=60)
    if inspect["returncode"] == 0:
        return {"ok": True, "renderer": renderer, "inspect": inspect, "built": False}
    build = build_renderer_image(profile)
    return {"ok": build.get("ok", False), "renderer": renderer, "inspect": inspect, "build": build, "built": True}


def path_within(path: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_project_path(root: pathlib.Path, raw: str, *, must_exist: bool = False) -> pathlib.Path:
    candidate = pathlib.Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not path_within(resolved, root):
        raise ValueError(f"path is outside the project root: {raw}")
    if must_exist and not resolved.is_file():
        raise FileNotFoundError(f"diagram source not found: {raw}")
    return resolved


def diagram_engine(input_path: pathlib.Path, requested: str = "auto") -> str:
    requested = (requested or "auto").strip().lower()
    if requested in {"mermaid", "plantuml"}:
        return requested
    suffix = input_path.suffix.lower()
    if suffix in {".mmd", ".mermaid"}:
        return "mermaid"
    if suffix in {".puml", ".plantuml", ".uml"}:
        return "plantuml"
    raise ValueError("engine must be mermaid or plantuml for sources without a known extension")


def diagram_engine_from_text(diagram_text: str, requested: str = "auto") -> str:
    requested = (requested or "auto").strip().lower()
    if requested in {"mermaid", "plantuml"}:
        return requested

    lines = [line.strip() for line in diagram_text.splitlines()]
    significant = [line for line in lines if line and not line.startswith(("%", "%%", "'", "//"))]
    first = significant[0].lower() if significant else ""
    if first.startswith("@start"):
        return "plantuml"
    if first.split(None, 1)[0] in MERMAID_TEXT_STARTS:
        return "mermaid"
    raise ValueError("engine must be mermaid or plantuml when diagram text cannot be inferred")


def resolve_style_name(engine: str, style: str) -> str:
    root = repo_dir()
    if engine == "mermaid":
        candidates = [style, f"{style.removesuffix('-mermaid')}-mermaid"]
        for candidate in candidates:
            if (root / "styles" / "mermaid" / f"{candidate}.json").is_file():
                return candidate
    elif engine == "plantuml":
        candidates = [style, f"{style.removesuffix('-plantuml')}-plantuml"]
        for candidate in candidates:
            if (root / "styles" / "plantuml" / f"{candidate}.puml").is_file():
                return candidate
    else:
        raise ValueError("engine must be mermaid or plantuml")
    raise FileNotFoundError(f"unknown {engine} style or family: {style}")


def container_path(path: pathlib.Path, root: pathlib.Path) -> str:
    return "/workspace/" + path.relative_to(root).as_posix()


def shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def validate_rendered_artifact(output: pathlib.Path, output_format: str) -> dict[str, Any]:
    if not output.is_file():
        return {"ok": False, "path": str(output), "reason": "output file was not created"}
    size = output.stat().st_size
    if size <= 0:
        return {"ok": False, "path": str(output), "bytes": size, "reason": "output file is empty"}

    header = output.read_bytes()[:4096]
    if output_format == "pdf" and not header.startswith(b"%PDF-"):
        return {"ok": False, "path": str(output), "bytes": size, "reason": "output is not a PDF"}
    if output_format == "png" and not header.startswith(b"\x89PNG\r\n\x1a\n"):
        return {"ok": False, "path": str(output), "bytes": size, "reason": "output is not a PNG"}
    if output_format == "svg" and b"<svg" not in header.lower():
        return {"ok": False, "path": str(output), "bytes": size, "reason": "output is not an SVG"}
    return {"ok": True, "path": str(output), "bytes": size, "format": output_format}


def render_diagram(
    project_root: str | pathlib.Path,
    *,
    input_path: str,
    output_path: str,
    engine: str = "auto",
    family: str = DEFAULT_FAMILY,
    style: str | None = None,
    profile: str = DEFAULT_COMPATIBILITY,
    output_format: str = "svg",
    dry_run: bool = False,
) -> dict[str, Any]:
    root = pathlib.Path(project_root).expanduser().resolve()
    source = resolve_project_path(root, input_path, must_exist=True)
    output = resolve_project_path(root, output_path)
    resolved_engine = diagram_engine(source, engine)
    output_format = (output_format or output.suffix.lstrip(".") or "svg").strip().lower()
    if output_format not in {"svg", "png", "pdf"}:
        raise ValueError("output_format must be svg, png, or pdf")

    renderer = renderer_profile(profile)
    if not renderer["ok"]:
        return {"ok": False, "renderer": renderer}

    style_query = (style or "").strip() or family
    style_name = resolve_style_name(resolved_engine, style_query)
    cache_suffix = ".mmd" if resolved_engine == "mermaid" else ".puml"
    styled = root / ".cache" / "diavisuals" / resolved_engine / f"{output.stem}{cache_suffix}"
    puppeteer = root / ".cache" / "diavisuals" / "puppeteer.json"
    style_source = [
        "/diavisuals/tools/style-diagram-source.sh",
        resolved_engine,
        style_name,
        container_path(source, root),
        container_path(styled, root),
    ]
    mkdirs = ["mkdir", "-p", container_path(output.parent, root), container_path(styled.parent, root), container_path(puppeteer.parent, root)]
    if resolved_engine == "mermaid":
        mermaid_config = f"/diavisuals/styles/mermaid/{style_name}.json"
        script = " && ".join(
            [
                shell_join(mkdirs),
                "printf '%s\\n' '{\"args\":[\"--no-sandbox\",\"--disable-setuid-sandbox\",\"--disable-dev-shm-usage\"]}' > "
                + shlex.quote(container_path(puppeteer, root)),
                shell_join(style_source),
                shell_join(
                    [
                        "mmdc",
                        "-i",
                        container_path(styled, root),
                        "-o",
                        container_path(output, root),
                        "-c",
                        mermaid_config,
                        "-p",
                        container_path(puppeteer, root),
                    ]
                ),
            ]
        )
    else:
        expected = output.parent / f"{styled.stem}.{output_format}"
        script = " && ".join(
            [
                shell_join(mkdirs),
                shell_join(style_source),
                shell_join(["plantuml", f"-t{output_format}", "-o", container_path(output.parent, root), container_path(styled, root)]),
                f"test -f {shlex.quote(container_path(expected, root))}",
                f"if [ {shlex.quote(container_path(expected, root))} != {shlex.quote(container_path(output, root))} ]; then mv {shlex.quote(container_path(expected, root))} {shlex.quote(container_path(output, root))}; fi",
            ]
        )

    uid_gid = f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") and hasattr(os, "getgid") else "1000:1000"
    command = [
        "docker",
        "run",
        "--rm",
        "--user",
        uid_gid,
        "-e",
        "HOME=/tmp",
        "-e",
        "JAVA_TOOL_OPTIONS=-Duser.home=/tmp",
        "-v",
        f"{root}:/workspace",
        "-v",
        f"{repo_dir()}:/diavisuals:ro",
        "-w",
        "/workspace",
        renderer["image"],
        "bash",
        "-lc",
        script,
    ]
    payload: dict[str, Any] = {
        "ok": True,
        "project": str(root),
        "engine": resolved_engine,
        "family": family,
        "style": style_name,
        "style_requested": style_query,
        "profile": profile.removesuffix(".env"),
        "input": rel(source, root),
        "output": rel(output, root),
        "styled_source": rel(styled, root),
        "renderer": renderer,
        "command": command,
    }
    if dry_run:
        payload["dry_run"] = True
        return payload

    image = ensure_renderer_image(profile)
    if not image.get("ok"):
        return {**payload, "ok": False, "image": image}
    output.parent.mkdir(parents=True, exist_ok=True)
    styled.parent.mkdir(parents=True, exist_ok=True)
    completed = run(command, cwd=root, timeout=300)
    artifact_check = validate_rendered_artifact(output, output_format)
    payload.update({
        "image": image,
        "result": completed,
        "artifact_check": artifact_check,
        "ok": completed["returncode"] == 0 and artifact_check["ok"],
    })
    return payload


def diagram_artifact_payload(output: pathlib.Path, root: pathlib.Path, output_format: str, *, include_data: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": rel(output, root),
        "mime_type": OUTPUT_MIME_TYPES.get(output_format, "application/octet-stream"),
        "format": output_format,
        "exists": output.is_file(),
    }
    if not output.is_file():
        return payload

    data = output.read_bytes()
    payload["bytes"] = len(data)
    if not include_data:
        return payload
    if output_format == "svg":
        payload["svg"] = data.decode("utf-8", errors="replace")
    else:
        payload["data_base64"] = base64.b64encode(data).decode("ascii")
    return payload


def render_diagram_text(
    project_root: str | pathlib.Path,
    *,
    diagram_text: str,
    output_path: str | None = None,
    engine: str = "auto",
    family: str = DEFAULT_FAMILY,
    style: str | None = None,
    profile: str = DEFAULT_COMPATIBILITY,
    output_format: str = "svg",
    include_data: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = pathlib.Path(project_root).expanduser().resolve()
    output_format = (output_format or "svg").strip().lower()
    if output_format not in OUTPUT_MIME_TYPES:
        raise ValueError("output_format must be svg, png, or pdf")
    resolved_engine = diagram_engine_from_text(diagram_text, engine)
    source_suffix = ".mmd" if resolved_engine == "mermaid" else ".puml"
    digest_values = {
        "engine": resolved_engine,
        "family": family,
        "style": style or "",
        "profile": profile,
        "output_format": output_format,
        "diagram_text": diagram_text,
    }
    digest = hashlib.sha256(json.dumps(digest_values, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    source = root / ".cache" / "diavisuals" / "inline" / resolved_engine / f"{digest}{source_suffix}"
    output = (
        resolve_project_path(root, output_path)
        if output_path
        else root / ".cache" / "diavisuals" / "outputs" / resolved_engine / f"{digest}.{output_format}"
    )

    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(diagram_text.rstrip() + "\n", encoding="utf-8")

    rendered = render_diagram(
        root,
        input_path=rel(source, root),
        output_path=rel(output, root),
        engine=resolved_engine,
        family=family,
        style=style,
        profile=profile,
        output_format=output_format,
        dry_run=dry_run,
    )
    payload = {
        **rendered,
        "inline": True,
        "input_text_sha256": hashlib.sha256(diagram_text.encode("utf-8")).hexdigest(),
        "input_source": rel(source, root),
        "artifact": diagram_artifact_payload(output, root, output_format, include_data=include_data)
        if not dry_run
        else {
            "path": rel(output, root),
            "mime_type": OUTPUT_MIME_TYPES[output_format],
            "format": output_format,
            "exists": False,
        },
    }
    return payload


def style_family_item(root: pathlib.Path, family: str) -> dict[str, Any]:
    mermaid_name = f"{family}-mermaid"
    plantuml_name = f"{family}-plantuml"
    mermaid_base = root / "styles" / "mermaid" / f"{mermaid_name}.json"
    mermaid_overrides = root / "styles" / "mermaid" / mermaid_name
    plantuml_base = root / "styles" / "plantuml" / f"{plantuml_name}.puml"
    plantuml_overrides = root / "styles" / "plantuml" / plantuml_name
    examples = root / "examples" / family
    tokens = root / "tokens" / f"{family}.yml"
    return {
        "family": family,
        "ok": mermaid_base.is_file() and plantuml_base.is_file(),
        "tokens": {"path": rel(tokens, root), "exists": tokens.is_file()},
        "mermaid": {
            "name": mermaid_name,
            "base": rel(mermaid_base, root),
            "base_exists": mermaid_base.is_file(),
            "overrides": [rel(path, root) for path in sorted(mermaid_overrides.glob("*.mmd"))] if mermaid_overrides.is_dir() else [],
            "examples": [rel(path, root) for path in sorted((examples / "mermaid").glob("*.mmd"))] if (examples / "mermaid").is_dir() else [],
        },
        "plantuml": {
            "name": plantuml_name,
            "base": rel(plantuml_base, root),
            "base_exists": plantuml_base.is_file(),
            "overrides": [rel(path, root) for path in sorted(plantuml_overrides.glob("*.puml"))] if plantuml_overrides.is_dir() else [],
            "examples": [rel(path, root) for path in sorted((examples / "plantuml").glob("*.puml"))] if (examples / "plantuml").is_dir() else [],
        },
    }


def style_inventory() -> dict[str, Any]:
    root = repo_dir()
    families: list[str] = []
    for style in sorted((root / "styles" / "mermaid").glob("*-mermaid.json")):
        family = style.name.removesuffix("-mermaid.json")
        if (root / "styles" / "plantuml" / f"{family}-plantuml.puml").is_file():
            families.append(family)
    items = [style_family_item(root, family) for family in families]
    return {
        "ok": all(item["ok"] for item in items),
        "repo": str(root),
        "git_head": git_head(root),
        "git_tag": git_tag(root),
        "families": items,
        "count": len(items),
    }


def compatibility_status(profile: str = DEFAULT_COMPATIBILITY) -> dict[str, Any]:
    root = repo_dir()
    compat_root = root / "compat"
    profile_path = pathlib.Path(profile)
    requested = profile_path.stem if profile_path.suffix == ".env" else profile_path.name
    profile_file = compat_root / f"{requested}.env"
    profiles = []
    for path in sorted(compat_root.glob("*.env")):
        values = parse_env(path)
        profiles.append(
            {
                "name": path.stem,
                "path": rel(path, root),
                "mermaid": values.get("MERMAID_CLI_VERSION"),
                "plantuml": values.get("PLANTUML_VERSION"),
                "family": values.get("DIAVISUALS_FAMILY"),
                "mermaid_types": values.get("MERMAID_TYPES"),
                "plantuml_types": values.get("PLANTUML_TYPES"),
            }
        )
    return {
        "ok": profile_file.is_file(),
        "requested": requested,
        "requested_path": rel(profile_file, root),
        "values": parse_env(profile_file),
        "profiles": profiles,
    }


def token_palette(root: pathlib.Path, family: str) -> dict[str, Any]:
    path = root / "tokens" / f"{family}.yml"
    if not path.is_file():
        return {
            "path": rel(path, root),
            "exists": False,
            "hex_colors": [],
            "hex_color_count": 0,
        }
    colors = sorted({match.group(0).upper() for match in HEX_COLOR_RE.finditer(path.read_text(encoding="utf-8"))})
    return {
        "path": rel(path, root),
        "exists": True,
        "hex_colors": colors,
        "hex_color_count": len(colors),
    }


def gallery_status(profile: str = DEFAULT_COMPATIBILITY, family: str = DEFAULT_FAMILY) -> dict[str, Any]:
    root = repo_dir()
    requested = profile.removesuffix(".env")
    gallery_root = root / "docs" / "gallery" / family / requested
    manifest = gallery_root / "manifest.csv"
    rows: list[dict[str, Any]] = []
    engines: dict[str, dict[str, Any]] = {}
    missing_outputs: list[str] = []
    non_rendered: list[dict[str, str]] = []

    if manifest.is_file():
        with manifest.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                engine = str(row.get("engine") or "")
                diagram_type = str(row.get("type") or "")
                status = str(row.get("status") or "")
                output = str(row.get("output") or "")
                output_path = root / output
                exists = output_path.is_file()
                if status != "rendered":
                    non_rendered.append({"engine": engine, "type": diagram_type, "status": status})
                if status == "rendered" and not exists:
                    missing_outputs.append(output)
                rows.append(
                    {
                        "engine": engine,
                        "type": diagram_type,
                        "status": status,
                        "output": output,
                        "exists": exists,
                    }
                )
                summary = engines.setdefault(
                    engine,
                    {
                        "rendered": 0,
                        "missing": 0,
                        "non_rendered": 0,
                        "types": [],
                    },
                )
                summary["types"].append(diagram_type)
                if status == "rendered" and exists:
                    summary["rendered"] += 1
                elif status == "rendered":
                    summary["missing"] += 1
                else:
                    summary["non_rendered"] += 1

    return {
        "ok": manifest.is_file() and not missing_outputs and not non_rendered,
        "profile": requested,
        "family": family,
        "gallery_root": rel(gallery_root, root),
        "manifest": {"path": rel(manifest, root), "exists": manifest.is_file()},
        "rendered_count": sum(1 for row in rows if row["status"] == "rendered" and row["exists"]),
        "row_count": len(rows),
        "engines": engines,
        "missing_outputs": missing_outputs,
        "non_rendered": non_rendered,
    }


def style_audit(profile: str = DEFAULT_COMPATIBILITY, family: str = DEFAULT_FAMILY) -> dict[str, Any]:
    root = repo_dir()
    inventory = style_inventory()
    compat = compatibility_status(profile)
    family_item = next((item for item in inventory["families"] if item["family"] == family), None)
    palette = token_palette(root, family)
    gallery = gallery_status(profile=profile, family=family)
    styles = {
        "family": family,
        "mermaid": f"{family}-mermaid",
        "plantuml": f"{family}-plantuml",
    }

    issues: list[str] = []
    if family_item is None:
        issues.append(f"missing style family: {family}")
    elif not family_item["ok"]:
        issues.append(f"incomplete style family: {family}")
    if not palette["exists"]:
        issues.append(f"missing token file: tokens/{family}.yml")
    if not compat["ok"]:
        issues.append(f"missing compatibility profile: {profile}")
    if not gallery["ok"]:
        issues.append(f"incomplete rendered gallery: {family}/{profile}")

    return {
        "ok": not issues,
        "issues": issues,
        "repo": str(root),
        "git_head": git_head(root),
        "git_tag": git_tag(root),
        "contract": {
            "source": "vendored-package-assets",
            "family": family,
            "compatibility": profile.removesuffix(".env"),
            "styles": styles,
        },
        "tokens": palette,
        "family": family_item,
        "compatibility": compat,
        "gallery": gallery,
    }


def check_styles(profile: str = DEFAULT_COMPATIBILITY, family: str = DEFAULT_FAMILY) -> dict[str, Any]:
    inventory = style_inventory()
    compat = compatibility_status(profile)
    family_item = next((item for item in inventory["families"] if item["family"] == family), None)
    issues: list[str] = []
    if family_item is None:
        issues.append(f"missing style family: {family}")
    elif not family_item["ok"]:
        issues.append(f"incomplete style family: {family}")
    if not compat["ok"]:
        issues.append(f"missing compatibility profile: {profile}")
    return {
        "ok": not issues,
        "issues": issues,
        "family": family_item,
        "compatibility": compat,
    }


def release_status(release: str = DEFAULT_RELEASE) -> dict[str, Any]:
    root = repo_dir()
    tag_result = run(["git", "-C", str(root), "rev-parse", "--verify", f"refs/tags/{release}"], cwd=root)
    current_tag = git_tag(root)
    return {
        "ok": tag_result["returncode"] == 0,
        "requested": release,
        "requested_sha": str(tag_result["stdout"]).strip() if tag_result["returncode"] == 0 else None,
        "current_head": git_head(root),
        "current_tag": current_tag,
        "current_matches_release": current_tag == release,
    }


def submodule_plan(
    project_root: str = ".",
    *,
    path: str = "docs/slides/resources/diavisuals",
    release: str = DEFAULT_RELEASE,
    remote: str = DEFAULT_REMOTE,
) -> dict[str, Any]:
    return {
        "ok": True,
        "project_root": project_root,
        "path": path,
        "release": release,
        "remote": remote,
        "commands": [
            ["git", "submodule", "add", remote, path],
            ["git", "-C", path, "checkout", release],
            ["git", "add", ".gitmodules", path],
        ],
    }


def update_factory(dry_run: bool = False) -> dict[str, Any]:
    root = repo_dir()
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "command": ["git", "pull", "--ff-only"],
            "repo": str(root),
        }
    status = run(["git", "-C", str(root), "status", "--porcelain"], cwd=root)
    if status["returncode"] != 0 or status["stdout"].strip():
        return {
            "ok": False,
            "message": "Refusing to update a dirty or unreadable diavisuals checkout.",
            "status": status,
        }
    result = run(["git", "-C", str(root), "pull", "--ff-only"], cwd=root, timeout=300)
    return {
        "ok": result["returncode"] == 0,
        "result": result,
        "git_head": git_head(root),
    }


def mcp_stdio_command(project: str = "${workspaceFolder}") -> list[str]:
    return ["make", "-C", str(repo_dir()), "mcp-stdio", f"PROJECT={project}"]


def client_config(project: str = "${workspaceFolder}", command: str = "") -> dict[str, Any]:
    server_command = [command, "--project", project, "mcp", "serve"] if command else mcp_stdio_command(project)
    return {
        "mcpServers": {
            "diavisuals": {
                "command": server_command[0],
                "args": server_command[1:],
            }
        }
    }


def vscode_client_config(project: str = "${workspaceFolder}", command: str = "") -> dict[str, Any]:
    server_command = [command, "--project", project, "mcp", "serve"] if command else mcp_stdio_command(project)
    return {
        "servers": {
            "diavisuals": {
                "type": "stdio",
                "command": server_command[0],
                "args": server_command[1:],
            }
        }
    }


def factory_manifest() -> dict[str, Any]:
    root = repo_dir()
    return {
        "ok": True,
        "name": "diavisuals",
        "kind": "codex-mcp-factory",
        "version": "0.1.2",
        "description": "Shared diagram style registry and Docker renderer for Mermaid and PlantUML.",
        "factory": str(root),
        "git_head": git_head(root),
        "workspace_rule": {
            "consumer_root": ".",
            "source_paths": [],
            "generated_paths": [".cache/diavisuals"],
            "init_creates": [".cache/diavisuals"],
            "allowed_external_writes": [],
        },
        "commands": {
            "build": ["make", "mcp-build"],
            "init": ["make", "mcp-init"],
            "check": ["diavisuals", "check"],
            "smoke": ["make", "mcp-smoke"],
            "update": ["diavisuals", "update"],
            "install_codex_mcp": ["diavisuals", "install-codex-mcp"],
            "client_config": ["diavisuals", "mcp", "client-config"],
            "serve": ["make", "mcp-stdio"],
            "manifest": ["diavisuals", "factory-manifest"],
            "styles": ["diavisuals", "style-inventory"],
            "audit": ["diavisuals", "style-audit"],
            "render": ["diavisuals", "render-diagram"],
            "render_text": ["diavisuals", "render-diagram-text"],
        },
        "mcp": {
            "server_name": "diavisuals",
            "transport": "stdio",
            "command": mcp_stdio_command("${workspaceFolder}"),
            "resources": [
                "diavisuals://agent-guide",
                "diavisuals://styles",
                "diavisuals://compatibility",
                "diavisuals://style-audit",
                "diavisuals://examples",
                "diavisuals://factory-manifest",
            ],
            "tools": [
                "style_inventory",
                "style_audit",
                "check_styles",
                "compatibility_status",
                "release_status",
                "submodule_plan",
                "render_diagram",
                "render_diagram_text",
                "update",
                "factory_manifest",
            ],
        },
        "release": {
            "default": DEFAULT_RELEASE,
            "compatibility": DEFAULT_COMPATIBILITY,
            "family": DEFAULT_FAMILY,
        },
    }


def install_check(command: str = "diavisuals") -> dict[str, Any]:
    resolved = shutil.which(command)
    result = None
    mcp_dependency = None
    if resolved:
        result = run([resolved, "--version"], cwd=repo_dir(), timeout=30)
        mcp_dependency = check_mcp_dependency(resolved)
    return {
        "ok": bool(
            resolved
            and result
            and result["returncode"] == 0
            and mcp_dependency
            and mcp_dependency["returncode"] == 0
        ),
        "command": command,
        "resolved": resolved,
        "version_result": result,
        "mcp_dependency": mcp_dependency,
        "install_hints": [
            "uv tool install --editable .",
            "uv tool install --editable '.[mcp]'",
        ],
    }


def entrypoint_python(command_path: str) -> str | None:
    try:
        first_line = pathlib.Path(command_path).read_text(encoding="utf-8", errors="ignore").splitlines()[0]
    except (IndexError, OSError, UnicodeDecodeError):
        return None
    if not first_line.startswith("#!"):
        return None
    executable = first_line[2:].strip().split()[0]
    if pathlib.Path(executable).exists():
        return executable
    return None


def check_mcp_dependency(command_path: str) -> dict[str, Any]:
    python = entrypoint_python(command_path)
    if not python:
        return {
            "returncode": 1,
            "stdout": "",
            "stderr": "Could not determine the Python interpreter used by the CLI entrypoint.",
            "command": [command_path],
        }
    return run(
        [python, "-c", "from mcp.server.fastmcp import FastMCP; print('ok')"],
        cwd=repo_dir(),
        timeout=30,
    )


def json_dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)

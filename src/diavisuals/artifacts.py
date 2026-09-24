"""Opt-in leaf diagram products for MCP artifact handoff v1.

Direct rendering and native provider receipts have independent lifecycles.
This adapter never imports bundles or grants deletion/replacement authority.
"""

from __future__ import annotations

import base64
import fcntl
import io
import os
import pathlib
import re
import stat
import tempfile
import uuid
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from typing import Any

from . import __version__
from . import registry as core
from .handoff_fs import (
    MAX_FILE,
    MAX_MANIFEST,
    Workspace,
    digest,
    json_bytes,
    parse_json,
    rename_new,
    require,
    safe_path,
    signature,
    unique_paths,
)

EXPORT_ROOT = ".diavisuals/artifacts"
STAGING_ROOT = f"{EXPORT_ROOT}/.staging"
ID_RE = re.compile(r"[a-z][a-z0-9._-]{0,79}\Z")
HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
REVISION_RE = re.compile(r"(?:git:(?:[0-9a-f]{40}|[0-9a-f]{64})|sha256:[0-9a-f]{64})\Z")
MAX_PRODUCT_BYTES = 256 * 1024 * 1024
ROLE_SEMANTICS = {
    "request": ("input", "producer"),
    "diagram-source": ("input", "author"),
    "render-resource": ("input", "producer"),
    "producer-source": ("evidence", "producer"),
    "producer-identity": ("evidence", "producer"),
    "render-evidence": ("evidence", "producer"),
    "diagram-generated": ("output", "producer"),
    "diagram-original": ("output", "author"),
    "diagram-edited": ("output", "author"),
}


def _identifier(value: str) -> str:
    require(isinstance(value, str) and ID_RE.fullmatch(value) is not None, "invalid bundle/file identifier")
    safe_path(value)
    return value


def _keys(value: dict, required: set[str], optional: set[str] = frozenset()) -> None:
    require(type(value) is dict and required <= value.keys() <= required | optional, "missing or unknown fields")


def _source_check(data: bytes, engine: str, *, resource: bool = False) -> None:
    """Fail closed on input features with an unbounded/implicit dependency closure.

    This is an export profile, not a general Mermaid/PlantUML security parser.
    Private networkless rendering remains mandatory even for accepted sources.
    """
    text = data.decode("utf-8")
    require(bool(text.strip()), "empty diagram source/resource")
    require(not re.search(r"(?i)(?:[a-z][a-z0-9+.-]*://|\b(?:url\s*\(|href\s*=|src\s*=)|@import|@font-face)", text),
            "unsupported source/resource dependency: URL, CSS or external reference")
    require("![" not in text, "unsupported source/resource dependency: embedded content")
    if engine == "plantuml":
        require("[[" not in text, "unsupported PlantUML dependency: linked content")
        checked = text
        if resource:
            # The shipped style's sole preprocessor use is a version fallback.
            checked = re.sub(r'(?m)^!if %version\(\) >= "1\.2021\.0"\s*$|^!(?:else|endif)\s*$', "", checked)
        require(not re.search(r"(?im)(?:!|%[a-z_]+\s*\(|<\s*img|\b(?:sprite|image|shapefile)\b)", checked),
                "unsupported PlantUML dependency: preprocessor, function, sprite or image")
        if not resource:
            starts = re.findall(r"(?im)^\s*@start(\w+)\b", text)
            ends = re.findall(r"(?im)^\s*@end(\w+)\b", text)
            require(len(starts) == 1 and starts == ends, "export requires exactly one PlantUML product")
            require(starts[0] in {"uml", "json", "yaml", "gantt", "salt", "files", "wbs", "mindmap"},
                    "unsupported PlantUML product in the portable export profile")
    else:
        require(not re.search(r"(?i)(?:\b(?:img|image|icon)\s*:|\bclick\b|<\s*(?!/?(?:br|b|i|em|strong)\s*/?>)[a-z/])", text),
                "unsupported Mermaid dependency: image, icon, HTML or click action")
        if not resource:
            require("%%{" not in text and not text.lstrip().startswith("---"),
                    "unsupported Mermaid dependency: source configuration/front matter; use retained package styles")


def _svg_check(data: bytes) -> None:
    text = data.decode("utf-8")
    require("\x00" not in text and not re.search(r"<!\s*(?:DOCTYPE|ENTITY)", text, re.I),
            "SVG declarations/entities are unsupported")
    try:
        parsed = ET.iterparse(io.BytesIO(data), events=("start", "pi"))
        count = 0
        for event, node in parsed:
            if event == "pi":
                # PlantUML emits inert version and encoded-source metadata PIs.
                # Neither is a stylesheet/resource instruction or executable input.
                require(re.fullmatch(r"(?:plantuml [0-9]+\.[0-9]+\.[0-9]+|plantuml-src [A-Za-z0-9_+/=\-]+)", node.text or "") is not None,
                        f"SVG resource processing instructions are unsupported: {(node.text or '').split(' ', 1)[0][:80]}")
            count += 1
            require(count <= 100000, "SVG node limit exceeded")
        root = parsed.root
    except ET.ParseError as exc:
        raise ValueError("invalid SVG XML") from exc
    require(root.tag in {"svg", "{http://www.w3.org/2000/svg}svg"}, "invalid SVG root")
    ids = [node.attrib["id"] for node in root.iter() if "id" in node.attrib]
    require(len(ids) == len(set(ids)), "duplicate SVG id")
    references = []

    def reference(value: str) -> None:
        if value.startswith("#"):
            references.append(value[1:])
        elif re.fullmatch(r"data:image/(?:png|jpeg);base64,[A-Za-z0-9+/=\s]+", value):
            encoded = value.split(",", 1)[1]
            decoded = base64.b64decode(re.sub(r"\s", "", encoded), validate=True)
            require(decoded.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")), "invalid embedded raster")
        else:
            raise ValueError("unsupported SVG dependency: only local fragments and embedded PNG/JPEG are supported")

    def css(value: str) -> None:
        require(not re.search(r"(?i)(?:\\|/\*|@import|@font-face|(?:expression|image-set|image|paint)\s*\()", value), "unsupported SVG CSS dependency")
        for item in re.findall(r"(?i)url\s*\((.*?)\)", value):
            reference(item.strip().strip("\"'"))

    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1].lower()
        require(not tag.startswith("animate") and tag not in {"script", "link", "iframe", "object", "embed", "audio", "video", "set"},
                "unsupported active SVG content")
        if tag == "style":
            css(node.text or "")
        for key, value in node.attrib.items():
            local = key.rsplit("}", 1)[-1].lower()
            require(not local.startswith("on") and local not in {"base", "srcset", "poster", "background", "action", "formaction"},
                    "unsupported SVG event/base/resource reference")
            if local in {"href", "src"}:
                reference(value)
            if local == "style" or "url" in value.lower():
                css(value)
    require(all(item in ids for item in references), "SVG references a missing local id")


def _output_check(data: bytes, output_format: str) -> None:
    require(0 < len(data) <= MAX_FILE, "output size is outside the export profile")
    if output_format == "svg":
        _svg_check(data)
    elif output_format == "png":
        require(data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR" and data[-8:-4] == b"IEND", "invalid PNG output")
    else:
        require(output_format == "pdf" and data.startswith(b"%PDF-") and data.rstrip().endswith(b"%%EOF"), "invalid PDF output")


@contextmanager
def _export_lock(workspace: Workspace):
    with workspace.directory(STAGING_ROOT, create=True) as fd:
        lock = os.open("export.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=fd)
        try:
            info = os.fstat(lock)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "unsafe export lock")
            fcntl.flock(lock, fcntl.LOCK_EX)
            require(signature(os.fstat(lock)) == signature(os.stat("export.lock", dir_fd=fd, follow_symlinks=False)), "export lock changed")
            workspace.snapshots[f"{STAGING_ROOT}/export.lock"] = signature(os.fstat(lock))
            yield
        finally:
            os.close(lock)


def _prepare(workspace: Workspace) -> None:
    """Opt-in ignore setup; append only, CAS-protect existing customizations."""
    root = workspace.root
    git = core.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"])
    is_git = git["returncode"] == 0
    if is_git:
        require(str(root) == git["stdout"].strip(), "Git export workspace must be its checkout root")
        tracked = core.run(["git", "-C", str(root), "ls-files", "--", STAGING_ROOT])
        require(tracked["returncode"] == 0 and not tracked["stdout"], "export recovery state is tracked; preserve and resolve it before enabling export")
    ignore = f"{EXPORT_ROOT}/.gitignore"
    try:
        before = workspace.read(ignore, MAX_MANIFEST)
    except FileNotFoundError:
        before = None
    rule = b"/.staging/"
    if before is None:
        workspace.write_new(ignore, rule + b"\n")
    elif rule not in before.splitlines():
        temporary = f"{STAGING_ROOT}/ignore-{uuid.uuid4().hex}"
        workspace.write_new(temporary, before + (b"\n" if before and not before.endswith(b"\n") else b"") + rule + b"\n",
                            mode=workspace.snapshots[ignore][2] & 0o777)
        workspace.recheck()
        with workspace.directory(EXPORT_ROOT) as parent, workspace.directory(STAGING_ROOT) as staging:
            require(signature(os.stat(".gitignore", dir_fd=parent, follow_symlinks=False)) == workspace.snapshots[ignore],
                    "ignore file changed before replacement")
            os.replace(temporary.rsplit("/", 1)[1], ".gitignore", src_dir_fd=staging, dst_dir_fd=parent)
            os.fsync(parent)
        workspace.snapshots.pop(ignore, None)
    if is_git:
        for probe in (f"{STAGING_ROOT}/", f"{STAGING_ROOT}/job/probe"):
            checked = core.run(["git", "-C", str(root), "check-ignore", "--no-index", "--quiet", "--", probe])
            require(checked["returncode"] == 0, "custom Git rules prevent effective export staging ignore coverage")
    workspace.read(ignore, MAX_MANIFEST)
    workspace.recheck()


def initialize_artifact_export(project_root: str | pathlib.Path) -> dict[str, Any]:
    with Workspace(project_root) as workspace, _export_lock(workspace):
        _prepare(workspace)
    return {"ok": True, "created": [EXPORT_ROOT, STAGING_ROOT], "cleanup": "explicit", "opt_in": True}


def _producer_sources() -> dict[str, bytes]:
    module_root = pathlib.Path(__file__).parent
    with Workspace(module_root) as workspace:
        sources = {f"payload/producer/{path.name}": workspace.read(path.name, package_asset=True) for path in sorted(module_root.glob("*.py"))}
        workspace.recheck()
    return sources


# Refuse to attribute a long-running server's loaded code to subsequently edited
# on-disk bytes. Restart after upgrades; do not claim an old Git HEAD as a pin.
_STARTUP_SOURCES = _producer_sources()


def _producer_snapshot() -> tuple[dict, dict[str, bytes]]:
    sources = _producer_sources()
    require(sources == _STARTUP_SOURCES, "producer package changed since startup; restart before exporting")
    inventory = [{"path": path, "sha256": digest(data), "bytes": len(data)} for path, data in sources.items()]
    identity = json_bytes({"profile": "diavisuals-python-sources-v1", "version": __version__, "files": inventory})
    actor = {"name": "diavisuals", "version": __version__, "revision": f"sha256:{digest(identity)}", "runtimes": []}
    sources["payload/producer/identity.json"] = identity
    return actor, sources


def _file_item(identity: str, path: str, data: bytes, kind: str, role: str, ownership: str = "producer", **extra) -> dict:
    return {"id": identity, "path": safe_path(path), "kind": kind, "role": role, "ownership": ownership,
            "sha256": digest(data), "bytes": len(data), **extra}


def _reject_composite_input(workspace: Workspace, path: str) -> None:
    """Do not silently strip upstream provenance from files inside sealed bundles."""
    parts = safe_path(path).split("/")
    for depth in range(len(parts)):
        marker = "/".join([*parts[:depth], "bundle.json"])
        try:
            manifest = workspace.read(marker, MAX_MANIFEST)
        except FileNotFoundError:
            continue
        require(parse_json(manifest).get("kind") != "mcp-artifact-bundle",
                "unsupported composite input: retain its complete upstream bundle through an integrator")


def _check_bundle(workspace: Workspace, path: str, sha256: str) -> dict:
    """Verify this producer's bounded leaf profile, not arbitrary composite bundles."""
    require(isinstance(sha256, str) and HASH_RE.fullmatch(sha256) is not None, "expected manifest SHA-256 is required")
    safe_path(path)
    base, _, name = path.rpartition("/")
    require(bool(base) and name == "bundle.json", "expected a bundle.json path")
    raw = workspace.read(path, MAX_MANIFEST)
    require(digest(raw) == sha256, "manifest SHA-256 mismatch")
    doc = parse_json(raw)
    _keys(doc, {"schema_version", "kind", "producer", "request", "files", "dependencies"})
    require(type(doc["schema_version"]) is int and doc["schema_version"] == 1
            and doc["kind"] == "mcp-artifact-bundle", "unsupported artifact schema")
    require(doc["dependencies"] == [], "diagram leaf export does not support composite inputs")
    actor = doc["producer"]
    _keys(actor, {"name", "version", "revision", "runtimes"})
    require(actor["name"] == "diavisuals" and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,79}", actor["version"])
            and REVISION_RE.fullmatch(actor["revision"]), "invalid producer identity")
    require(type(actor["runtimes"]) is list and len(actor["runtimes"]) == 1, "expected one immutable renderer runtime")
    runtime = actor["runtimes"][0]
    _keys(runtime, {"name", "revision"})
    require(runtime["name"] == "diavisuals-renderer" and core.DOCKER_IMAGE_ID_RE.fullmatch(runtime["revision"]), "invalid renderer revision")
    require(type(doc["files"]) is list and 2 <= len(doc["files"]) <= 10000, "invalid file inventory")
    files = {}
    data = {}
    product_bytes = 0
    for item in doc["files"]:
        _keys(item, {"id", "path", "kind", "role", "ownership", "sha256", "bytes"}, {"variant_of"})
        identity = _identifier(item["id"])
        require(identity not in files, "duplicate file id")
        _identifier(item["role"])
        require(item["kind"] in {"input", "output", "evidence"} and item["ownership"] in {"author", "producer"}, "invalid file semantics")
        if item["role"] in ROLE_SEMANTICS:
            require((item["kind"], item["ownership"]) == ROLE_SEMANTICS[item["role"]],
                    f"role ownership/kind mismatch: {item['role']}")
        require(safe_path(item["path"]).startswith("payload/") and HASH_RE.fullmatch(item["sha256"]), "invalid payload/hash")
        require(type(item["bytes"]) is int and 0 <= item["bytes"] <= MAX_FILE, "invalid file size")
        product_bytes += item["bytes"]
        require(product_bytes <= MAX_PRODUCT_BYTES, "diagram product exceeds the 256 MiB owner limit")
        content = workspace.read(f"{base}/{item['path']}")
        require((digest(content), len(content)) == (item["sha256"], item["bytes"]), f"payload hash/size mismatch: {item['path']}")
        files[identity] = item
        data[item["path"]] = content
    unique_paths([item["path"] for item in files.values()])
    require(workspace.inventory(base) == {"bundle.json", *data}, "bundle tree differs from declared inventory")
    for item in files.values():
        if "variant_of" in item:
            original = files.get(item["variant_of"], {})
            require(item["ownership"] == "author" and original.get("kind") == item["kind"]
                    and original is not item and "variant_of" not in original, "invalid original/variant relationship")
    request_file = files.get(doc["request"], {})
    require(request_file.get("kind") == "input" and request_file.get("role") == "request", "missing retained request")
    request = parse_json(data[request_file["path"]])
    _check_domain(request, files, data, actor)
    workspace.recheck()
    return doc


def _check_domain(request: dict, files: dict, data: dict[str, bytes], actor: dict) -> None:
    _keys(request, {"profile_version", "engine", "family", "style", "profile", "output_format", "source", "source_origin",
                    "resources", "generated", "original", "edits", "selection_origin", "renderer", "producer_identity"})
    require(type(request["profile_version"]) is int and request["profile_version"] == 1, "unsupported diagram request profile")
    engine = request["engine"]
    require(engine in {"mermaid", "plantuml"}, "unsupported diagram engine")
    require(request["output_format"] in {"svg", "png", "pdf"}, "unsupported output format")
    require(core.STYLE_NAME_RE.fullmatch(request["style"]) is not None, "invalid retained style")
    require(core.STYLE_NAME_RE.fullmatch(request["profile"]) is not None and core.STYLE_NAME_RE.fullmatch(request["family"]) is not None,
            "invalid retained profile/family")
    origin = request["source_origin"]
    require(type(origin) is dict and origin.get("kind") in {"file", "inline"}, "invalid source origin")
    _keys(origin, {"kind", "path"} if origin["kind"] == "file" else {"kind"})
    if origin["kind"] == "file":
        safe_path(origin["path"])
    by_path = {item["path"]: item for item in files.values()}

    def retained(path: str, kind: str, role: str) -> bytes:
        require(path in by_path and by_path[path]["kind"] == kind and by_path[path]["role"] == role, f"missing retained {role}: {path}")
        return data[path]

    source = retained(request["source"], "input", "diagram-source")
    require(len(source) <= core.MAX_DIAGRAM_SOURCE_BYTES, "diagram source exceeds byte limit")
    _source_check(source, engine)
    evidence = parse_json(retained("payload/render-evidence.json", "evidence", "render-evidence"))
    _keys(evidence, {"renderer", "returncode", "runtime_teardown_verified", "network", "consumer_mount", "source_sha256", "selected_original", "selected_edits"})
    require(evidence["renderer"] == request["renderer"] and evidence["runtime_teardown_verified"] is True
            and evidence["network"] == "none" and evidence["consumer_mount"] is False
            and type(evidence["returncode"]) is int and evidence["returncode"] == 0
            and evidence["source_sha256"] == digest(source), "invalid retained render evidence")
    suffix = "mmd" if engine == "mermaid" else "puml"
    require(request["source"] == f"payload/render/input/source.{suffix}", "invalid retained source layout")
    resources = request["resources"]
    require(type(resources) is list and len(resources) == len(set(resources)), "invalid resource inventory")
    required = {f"payload/render/tools/{name}" for name in ("render-one.sh", "style-diagram-source.sh", "resolve-style-name.sh")}
    required.add(f"payload/render/styles/{engine}/{request['style']}.{'json' if engine == 'mermaid' else 'puml'}")
    required.add(f"payload/resources/{request['profile']}.env")
    if engine == "mermaid" and request["output_format"] == "svg":
        required.add("payload/render/tools/normalize-mermaid-svg.py")
    require(required <= set(resources), "incomplete render resource closure")
    require(set(resources) == {item["path"] for item in files.values() if item["role"] == "render-resource"}, "resource inventory mismatch")
    for path in resources:
        content = retained(path, "input", "render-resource")
        if "/styles/" in path:
            _source_check(content, engine, resource=True)
    require(request["renderer"] == actor["runtimes"][0]["revision"], "request/runtime mismatch")
    identity = retained(request["producer_identity"], "evidence", "producer-identity")
    require(actor["revision"] == f"sha256:{digest(identity)}", "producer snapshot revision mismatch")
    code = parse_json(identity)
    _keys(code, {"profile", "version", "files"})
    require(code["profile"] == "diavisuals-python-sources-v1" and code["version"] == actor["version"], "invalid producer snapshot")
    require({item["path"] for item in code["files"]} == {item["path"] for item in files.values() if item["role"] == "producer-source"},
            "incomplete producer snapshot")
    for item in code["files"]:
        _keys(item, {"path", "sha256", "bytes"})
        content = retained(item["path"], "evidence", "producer-source")
        require((digest(content), len(content)) == (item["sha256"], item["bytes"]), "producer source mismatch")
    generated = retained(request["generated"], "output", "diagram-generated")
    _output_check(generated, request["output_format"])
    outputs = {request["generated"]}
    if request["original"] is not None:
        original = retained(request["original"], "output", "diagram-original")
        _svg_check(original)
        outputs.add(request["original"])
    require(type(request["edits"]) is list and len(request["edits"]) <= 32, "invalid edited variants")
    require(len(request["edits"]) == len(set(request["edits"])) and bool(request["edits"]) == bool(request["original"]), "invalid original/edited selection")
    require(evidence["selected_original"] == request["original"] and evidence["selected_edits"] == request["edits"],
            "original/edited selection evidence mismatch")
    selection_origin = request["selection_origin"]
    _keys(selection_origin, {"original", "edits"})
    require(type(selection_origin["edits"]) is list and len(selection_origin["edits"]) == len(request["edits"])
            and (selection_origin["original"] is None) == (request["original"] is None), "invalid selection origin")
    if request["original"] is not None:
        unique_paths([selection_origin["original"], *selection_origin["edits"]])
    for path in request["edits"]:
        require(request["original"] is not None, "edited variant requires its selected original")
        _svg_check(retained(path, "output", "diagram-edited"))
        require(by_path[path].get("variant_of") == by_path[request["original"]]["id"], "edited variant lost its original")
        outputs.add(path)
    require(outputs == {item["path"] for item in files.values() if item["kind"] == "output"}, "output inventory mismatch")


def check_diagram_bundle(project_root: str | pathlib.Path, *, path: str, sha256: str) -> dict[str, Any]:
    with Workspace(project_root) as workspace:
        doc = _check_bundle(workspace, path, sha256)
    return {"ok": True, "bundle": {"path": path, "sha256": sha256}, "files": len(doc["files"]), "domain_checked": True}


def _publish(workspace: Workspace, staged: str, bundle_id: str, sha256: str) -> dict[str, str]:
    destination = f"{EXPORT_ROOT}/{_identifier(bundle_id)}"
    with Workspace(workspace.root) as verifier:
        _check_bundle(verifier, f"{staged}/bundle.json", sha256)
        with workspace.directory(STAGING_ROOT) as source_fd, workspace.directory(EXPORT_ROOT) as target_fd:
            require(not any(name.casefold() == bundle_id.casefold() for name in os.listdir(target_fd)), "bundle destination already exists or is case-aliased")
            workspace.recheck()
            verifier.recheck()
            rename_new(source_fd, staged.rsplit("/", 1)[1], target_fd, bundle_id)
    check_diagram_bundle(workspace.root, path=f"{destination}/bundle.json", sha256=sha256)
    return {"path": f"{destination}/bundle.json", "sha256": sha256}


def recover_diagram_bundle(project_root: str | pathlib.Path, *, path: str, sha256: str, bundle_id: str) -> dict[str, Any]:
    safe_path(path)
    parts = path.split("/")
    require(path.startswith(f"{STAGING_ROOT}/") and len(parts) == 5 and parts[-1] == "bundle.json", "recovery requires an exact staging bundle.json")
    with Workspace(project_root) as workspace, _export_lock(workspace):
        _prepare(workspace)
        # A crash may have happened after rename but before its acknowledgement.
        destination = f"{EXPORT_ROOT}/{_identifier(bundle_id)}/bundle.json"
        try:
            with workspace.directory(path.rpartition("/")[0]):
                pass
        except FileNotFoundError:
            checked = check_diagram_bundle(project_root, path=destination, sha256=sha256)
            return {**checked, "recovered": True, "already_published": True}
        result = _publish(workspace, path.rpartition("/")[0], bundle_id, sha256)
    return {"ok": True, "bundle": result, "recovered": True}


def export_diagram_bundle(
    project_root: str | pathlib.Path, *, input_path: str | None = None, diagram_text: str | None = None,
    bundle_id: str = "", engine: str = "auto", family: str = core.DEFAULT_FAMILY, style: str = "",
    profile: str = core.DEFAULT_COMPATIBILITY, output_format: str = "svg", original_path: str | None = None,
    edited_paths: list[str] | None = None, dry_run: bool = False,
) -> dict[str, Any]:
    require((input_path is None) != (diagram_text is None), "provide exactly one of input_path or diagram_text")
    require(engine in {"auto", "mermaid", "plantuml"}, "engine must be auto, mermaid or plantuml")
    bundle_id = _identifier(bundle_id or f"diagram-{uuid.uuid4().hex}")
    output_format = core.resolve_output_format(None, output_format)
    edits = edited_paths or []
    require(len(edits) <= 32 and len(edits) == len(set(edits)), "at most 32 distinct edited variants are supported")
    require(bool(original_path) == bool(edits), "selected edits require original_path, and original_path requires edited_paths")
    if original_path:
        unique_paths([original_path, *edits])
        require(all(path.endswith(".svg") for path in [original_path, *edits]), "selected original/edited variants must be self-contained SVGs")
    staged = ""
    sha256 = ""
    with Workspace(project_root) as workspace:
        for path in ([input_path] if input_path is not None else []) + ([original_path, *edits] if original_path else []):
            _reject_composite_input(workspace, path)
        source_data = workspace.read(safe_path(input_path), core.MAX_DIAGRAM_SOURCE_BYTES) if input_path is not None else diagram_text.encode("utf-8")
        require(bool(source_data.strip()) and len(source_data) <= core.MAX_DIAGRAM_SOURCE_BYTES, "diagram source is empty or exceeds byte limit")
        engine = core.diagram_engine(pathlib.Path(input_path), engine) if input_path is not None else core.diagram_engine_from_text(diagram_text, engine)
        _source_check(source_data, engine)
        renderer = core.renderer_profile(profile)
        require(renderer["ok"], f"unsupported renderer profile: {renderer['issues']}")
        profile = renderer["profile"]
        style_name = core.resolve_style_name(engine, style or family)
        require(core.STYLE_NAME_RE.fullmatch(family) is not None, "invalid style family")
        originals = {}
        for path in ([original_path, *edits] if original_path else []):
            originals[path] = workspace.read(path)
            require(sum(map(len, originals.values())) <= MAX_PRODUCT_BYTES - core.MAX_DIAGRAM_SOURCE_BYTES,
                    "selected variants exceed the diagram product limit")
        for content in originals.values():
            _svg_check(content)
        if dry_run:
            return {"ok": True, "dry_run": True, "engine": engine, "style": style_name,
                    "bundle_path": f"{EXPORT_ROOT}/{bundle_id}/bundle.json", "opt_in": True}
        with _export_lock(workspace):
            _prepare(workspace)
            with workspace.directory(EXPORT_ROOT) as fd:
                require(not any(name.casefold() == bundle_id.casefold() for name in os.listdir(fd)), "bundle destination already exists or is case-aliased")
            staged = f"{STAGING_ROOT}/job-{uuid.uuid4().hex}"
            files = []

            def retain(identity: str, path: str, content: bytes, kind: str, role: str, ownership: str = "producer", **extra) -> None:
                require(len(content) <= MAX_FILE and sum(item["bytes"] for item in files) + len(content) <= MAX_PRODUCT_BYTES,
                        "diagram product exceeds the owner byte limits")
                executable = role == "render-resource" and path.startswith("payload/render/tools/") and path.endswith(".sh")
                workspace.write_new(f"{staged}/{path}", content, mode=0o700 if executable else 0o600)
                files.append(_file_item(identity, path, content, kind, role, ownership, **extra))

            try:
                suffix = "mmd" if engine == "mermaid" else "puml"
                source = f"payload/render/input/source.{suffix}"
                retain("source", source, source_data, "input", "diagram-source", "author")
                actor, producer_files = _producer_snapshot()
                for index, (path, content) in enumerate(producer_files.items()):
                    role = "producer-identity" if path.endswith("/identity.json") else "producer-source"
                    retain(f"producer-{index}", path, content, "evidence", role)
                original = "payload/outputs/original.svg" if original_path else None
                if original:
                    retain("original", original, originals[original_path], "output", "diagram-original", "author")
                edited = []
                for index, path in enumerate(edits):
                    exported = f"payload/outputs/edited-{index + 1}.svg"
                    retain(f"edited-{index + 1}", exported, originals[path], "output", "diagram-edited", "author", variant_of="original")
                    edited.append(exported)
                image = core.ensure_renderer_image(profile)
                require(image.get("ok") and core.DOCKER_IMAGE_ID_RE.fullmatch(str(image.get("image_id", ""))), "renderer did not resolve to an immutable image ID")
                image_id = image["image_id"]
                actor["runtimes"] = [{"name": "diavisuals-renderer", "revision": image_id}]
                with tempfile.TemporaryDirectory(prefix="diavisuals-export-render-") as temporary:
                    private = pathlib.Path(temporary)
                    require(not core.path_within(private, workspace.root), "renderer staging must be outside the consumer workspace")
                    stage = core.stage_renderer_bundle(private, source=pathlib.Path(source), source_data=source_data,
                                                       engine=engine, style_name=style_name, output_format=output_format, strict_assets=True)
                    resources = []
                    with Workspace(stage["bundle"]) as assets:
                        for index, path in enumerate(sorted(assets.inventory(""))):
                            content = assets.read(path)
                            if path.startswith("input/"):
                                require(content == source_data, "staged source mismatch")
                                continue
                            if path.startswith("styles/"):
                                _source_check(content, engine, resource=True)
                            exported = f"payload/render/{path}"
                            retain(f"resource-{index}", exported, content, "input", "render-resource")
                            resources.append(exported)
                        assets.recheck()
                    with Workspace(core.repo_dir()) as package:
                        content = package.read(f"compat/{profile}.env", MAX_MANIFEST, package_asset=True)
                        require(core.parse_env(core.repo_dir() / f"compat/{profile}.env") == renderer["values"], "profile changed during export")
                        package.recheck()
                    profile_path = f"payload/resources/{profile}.env"
                    retain("profile", profile_path, content, "input", "render-resource")
                    resources.append(profile_path)
                    generated = f"payload/outputs/generated.{output_format}"
                    request = {
                        "profile_version": 1, "engine": engine, "family": family, "style": style_name, "profile": profile,
                        "output_format": output_format, "source": source,
                        "source_origin": {"kind": "file", "path": input_path} if input_path is not None else {"kind": "inline"},
                        "resources": resources, "generated": generated, "original": original, "edits": edited,
                        "selection_origin": {"original": original_path, "edits": edits},
                        "renderer": image_id, "producer_identity": "payload/producer/identity.json",
                    }
                    retain("request", "payload/request.json", json_bytes(request), "input", "request")
                    name = core.renderer_container_name(workspace.root)
                    command = core.build_renderer_command(root=workspace.root, renderer={**renderer, "image": image_id},
                                                          engine=engine, style_name=style_name, output_format=output_format,
                                                          bundle=stage["bundle"], result=stage["result"], cidfile=stage["cidfile"], container_name=name)
                    completed = core._run_renderer(command, container_name=name, cwd=workspace.root)
                    require(completed["returncode"] == 0 and completed["cleanup"]["ok"], "renderer failed or runtime teardown was not verified")
                    with Workspace(stage["bundle"]) as actual:
                        inventory = actual.inventory("")
                        expected = {item["path"].removeprefix("payload/render/"): item for item in files
                                    if item["path"].startswith("payload/render/")}
                        require(inventory == expected.keys(), "render resources changed during rendering")
                        for path, item in expected.items():
                            require(digest(actual.read(path)) == item["sha256"], "render input/resource changed during rendering")
                        actual.recheck()
                    with Workspace(stage["result"]) as result:
                        artifact = result.read(f"artifact.{output_format}")
                        result.recheck()
                    _output_check(artifact, output_format)
                    retain("generated", generated, artifact, "output", "diagram-generated")
                    retain("render-evidence", "payload/render-evidence.json", json_bytes({
                        "renderer": image_id, "returncode": 0, "runtime_teardown_verified": True,
                        "network": "none", "consumer_mount": False, "source_sha256": digest(source_data),
                        "selected_original": original, "selected_edits": edited,
                    }), "evidence", "render-evidence")
                workspace.recheck()
                require(_producer_snapshot()[0]["revision"] == actor["revision"], "producer package changed during export")
                manifest = json_bytes({"schema_version": 1, "kind": "mcp-artifact-bundle", "producer": actor,
                                       "request": "request", "files": files, "dependencies": []})
                require(len(manifest) <= MAX_MANIFEST, "manifest byte limit exceeded")
                workspace.write_new(f"{staged}/bundle.json", manifest)
                sha256 = digest(manifest)
                bundle = _publish(workspace, staged, bundle_id, sha256)
                return {"ok": True, "bundle": bundle, "engine": engine, "producer": actor, "opt_in": True}
            except (OSError, ValueError) as exc:
                # Never delete a partially written or sealed job, even after rename/fsync failure.
                return {"ok": False, "error": str(exc), "recovery": {"path": f"{staged}/bundle.json", "sha256": sha256 or None,
                        "destination": f"{EXPORT_ROOT}/{bundle_id}/bundle.json"}, "cleanup": "explicit"}

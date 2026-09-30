"""Native runtime selection, independent of the bytes of compatibility profiles."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

IMAGE_ID_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
IMAGE_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:\-]*\Z")
IMAGE_DIGEST_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:\-]*@sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class RuntimeSelection:
    """An explicit ref is inspect-only; an empty selection retains profile behavior.

    Tags require an expected config/image ID. A full image ID pins itself. A
    repository digest pins the manifest (and may additionally pin the image ID).
    Never mix a partially supplied argument pair with values from the environment.
    """

    image_ref: str | None = None
    expected_image_id: str | None = None

    def __post_init__(self) -> None:
        ref, expected = self.image_ref, self.expected_image_id
        if ref is None and expected is None:
            return
        if not isinstance(ref, str) or not ref or ref != ref.strip():
            raise ValueError("explicit runtime selection requires a non-empty image ref")
        if expected is not None and (not isinstance(expected, str) or not IMAGE_ID_RE.fullmatch(expected)):
            raise ValueError("expected runtime image ID must be sha256:<64 lowercase hex digits>")
        if ref.startswith("sha256:"):
            if not IMAGE_ID_RE.fullmatch(ref):
                raise ValueError("runtime image ID must be a complete sha256 identity")
            if expected is not None and expected != ref:
                raise ValueError("runtime ref and expected image ID do not match")
            object.__setattr__(self, "expected_image_id", ref)
        elif "@" in ref:
            if not IMAGE_DIGEST_RE.fullmatch(ref):
                raise ValueError("runtime repository digest must be <repository>@sha256:<64 lowercase hex digits>")
        elif not IMAGE_REF_RE.fullmatch(ref) or expected is None:
            raise ValueError("a runtime alias requires a valid ref and an expected immutable image ID")

    @property
    def explicit(self) -> bool:
        return self.image_ref is not None

    @property
    def repository_digest(self) -> str | None:
        return self.image_ref if self.image_ref and "@" in self.image_ref else None

    def environment(self) -> dict[str, str]:
        """Serialize this frozen selection for child CLI/MCP processes."""
        if not self.explicit:
            return {}
        values = {"DIAVISUALS_RUNTIME_IMAGE": self.image_ref}
        if self.expected_image_id:
            values["DIAVISUALS_RUNTIME_EXPECTED_ID"] = self.expected_image_id
        return values


def runtime_selection(image_ref: str | None = None, expected_image_id: str | None = None) -> RuntimeSelection:
    if image_ref is not None or expected_image_id is not None:
        return RuntimeSelection(image_ref, expected_image_id)
    return RuntimeSelection(os.environ.get("DIAVISUALS_RUNTIME_IMAGE"), os.environ.get("DIAVISUALS_RUNTIME_EXPECTED_ID"))


def validate_runtime_identity(identity: dict, *, image_id: str, profile_sha256: str, profile_ref: str) -> None:
    """Offline consistency of retained native evidence, independent of today's selection."""
    fields = {"mode", "requested_ref", "expected_image_id", "image_id", "profile_sha256"}
    if not isinstance(identity, dict) or set(identity) != fields:
        raise ValueError("invalid runtime selection evidence fields")
    if identity["image_id"] != image_id or not IMAGE_ID_RE.fullmatch(image_id):
        raise ValueError("runtime selection/effective image mismatch")
    if identity["profile_sha256"] != profile_sha256:
        raise ValueError("runtime selection/profile bytes mismatch")
    if identity["mode"] == "explicit":
        selected = RuntimeSelection(identity["requested_ref"], identity["expected_image_id"])
        if not selected.explicit or (selected.expected_image_id is not None and selected.expected_image_id != image_id):
            raise ValueError("runtime selection/expected identity mismatch")
    elif identity["mode"] != "profile" or identity["expected_image_id"] is not None or identity["requested_ref"] != profile_ref:
        raise ValueError("runtime selection/profile ref mismatch")

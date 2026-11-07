"""Checks on an Office package (a zip file) BEFORE any library parses it. Pure standard library; the file is never opened by an application.

* Allow-list of extensions: only `.xlsx` and `.docx`; macro-capable formats are named and refused (also when only the extension was changed).
* The container is inspected: macro/active parts (VBA project, ActiveX, OLE/embedded objects, external links, macro sheets, custom UI), macro content
  types, encrypted members, unsafe member names.
* Bomb guard: entry count, declared AND actually unpacked size (counted while reading, so lying headers do not help), compression ratio.
* XML parts must not contain a DTD or entity declarations (no real Office file needs them): "billion laughs" / external entities are refused up front.
"""
from __future__ import annotations

import io
import posixpath
import zipfile
from dataclasses import dataclass

from jarvis.files.errors import FilesError

ALLOWED = {".xlsx": "xlsx", ".docx": "docx"}
MACRO_FORMATS = frozenset({".xlsm", ".xlsb", ".xls", ".xltm", ".xltx", ".xlam", ".xla", ".docm", ".dotm", ".dotx", ".doc", ".dot", ".pptm", ".potm", ".ppam",
                           ".ppsm", ".ppt", ".pptx", ".pps"})
MAIN_PART = {"xlsx": "xl/workbook.xml", "docx": "word/document.xml"}
# lower-case fragments of member names that mean macros, active content, embedded objects or live links
ACTIVE_PARTS = ("vbaproject", "vbadata", "/activex/", "activex/", "/embeddings/", "embeddings/", "oleobject", "/externallinks/", "externallinks/",
                "macrosheets/", "dialogsheets/", "customui/", "/macros/")
ACTIVE_TYPES = (b"macroenabled", b"vbaproject", b"vbadata", b"activex", b"oleobject", b"externallink")
MAX_RATIO = 200          # compressed -> unpacked for one member (above 1 MB)
_CHUNK = 64 * 1024


@dataclass(frozen=True)
class PackageLimits:
    max_file_size: int
    max_unpacked_bytes: int
    max_zip_entries: int


def _bad(code: str, message: str) -> FilesError:
    return FilesError(code, message)


def kind_for(path: str) -> str:
    """'xlsx' | 'docx'. Anything else is refused with a message that names what is supported."""
    ext = posixpath.splitext(path.replace("\\", "/"))[1].lower()
    if ext in ALLOWED:
        return ALLOWED[ext]
    if ext in MACRO_FORMATS:
        raise _bad("unsupported_format", f"'{ext}' is refused (macro-capable or unsupported format); only .xlsx and .docx are handled and macros are never run")
    raise _bad("unsupported_format", "only .xlsx and .docx files are supported")


def inspect_package(data: bytes, kind: str, limits: PackageLimits) -> None:
    """Raise FilesError unless `data` is a plain Office Open XML package without macros/active content and within the bomb limits."""
    if len(data) > limits.max_file_size:
        raise _bad("file_too_large", f"the file is larger than {limits.max_file_size} bytes")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError, ValueError):
        raise _bad("invalid_package", "the file is not a valid Office package (not a zip container)") from None
    with zf:
        infos = zf.infolist()
        if len(infos) > limits.max_zip_entries:
            raise _bad("zip_bomb", f"the package has more than {limits.max_zip_entries} entries")
        declared = sum(i.file_size for i in infos)
        if declared > limits.max_unpacked_bytes:
            raise _bad("zip_bomb", f"the package would unpack to more than {limits.max_unpacked_bytes} bytes")
        names = {i.filename for i in infos}
        if MAIN_PART[kind] not in names or "[Content_Types].xml" not in names:
            raise _bad("invalid_package", f"the file is not a valid {kind} package (main part missing)")
        total = 0
        for info in infos:
            name = info.filename
            low = name.lower()
            if name.startswith(("/", "\\")) or ".." in name.replace("\\", "/").split("/") or ":" in name or "\x00" in name:
                raise _bad("invalid_package", "the package contains an unsafe member name")
            if any(frag in low for frag in ACTIVE_PARTS):
                raise _bad("macros_refused", "the package contains macros or active content (VBA, ActiveX, embedded objects, external links); it is not loaded")
            if info.flag_bits & 0x1:
                raise _bad("invalid_package", "the package contains encrypted members")
            if info.file_size > 1_000_000 and info.compress_size and info.file_size / info.compress_size > MAX_RATIO:
                raise _bad("zip_bomb", "a package member has an implausible compression ratio")
            if info.is_dir():
                continue
            is_xml = low.endswith((".xml", ".rels", ".vml"))
            head = b""
            size = 0
            try:
                with zf.open(info) as fh:
                    while chunk := fh.read(_CHUNK):
                        size += len(chunk)
                        total += len(chunk)
                        if total > limits.max_unpacked_bytes or size > max(info.file_size, 0) + _CHUNK:
                            raise _bad("zip_bomb", f"the package unpacks to more than {limits.max_unpacked_bytes} bytes")
                        if is_xml:
                            scan = (head[-16:] + chunk).lower()
                            if chunk.startswith((b"\xff\xfe", b"\xfe\xff")) and not head:
                                raise _bad("invalid_package", "XML parts in UTF-16 are not accepted")
                            if b"<!doctype" in scan or b"<!entity" in scan:
                                raise _bad("xml_entities_refused", "an XML part declares a DTD or entities (entity expansion); the package is not loaded")
                            if low == "[content_types].xml" and any(t in scan for t in ACTIVE_TYPES):
                                raise _bad("macros_refused", "the package declares macro or active content types; it is not loaded")
                            head = chunk
            except FilesError:
                raise
            except (zipfile.BadZipFile, OSError, ValueError, EOFError, RuntimeError, NotImplementedError):
                raise _bad("invalid_package", "the package is damaged or uses an unsupported compression") from None

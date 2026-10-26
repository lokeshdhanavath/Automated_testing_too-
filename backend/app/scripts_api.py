
import ast
import os
import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


# Project root: C:\Users\lokesh.dhanavath\apex
PROJECT_ROOT = Path(__file__).resolve().parents[3]
TESTS_DIR = (PROJECT_ROOT / "tests").resolve()

router = APIRouter(prefix="/api/scripts", tags=["Test Scripts"])

# Only filenames matching this pattern can be managed through the UI.
# This API never accepts arbitrary paths from the browser.
SCRIPT_NAME_PATTERN = re.compile(r"test_[a-zA-Z0-9_-]+\.py\Z")


class ScriptCreateRequest(BaseModel):
    filename: str = Field(min_length=8, max_length=100)
    content: str = Field(min_length=1, max_length=500_000)


class ScriptUpdateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=500_000)


def validate_filename(filename: str) -> str:
    """Accept only simple pytest test filenames."""
    if not SCRIPT_NAME_PATTERN.fullmatch(filename):
        raise HTTPException(
            status_code=400,
            detail="Filename must match test_<name>.py and contain only letters, numbers, underscores, or hyphens.",
        )

    return filename


def resolve_script(filename: str) -> Path:
    """Resolve a script and ensure it remains directly inside tests/."""
    validate_filename(filename)

    path = (TESTS_DIR / filename).resolve()

    if path.parent != TESTS_DIR:
        raise HTTPException(status_code=400, detail="Invalid script path.")

    return path


def read_script(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to read script: {exc}",
        ) from exc


def validate_python(content: str) -> None:
    """Reject syntactically invalid Python before saving."""
    try:
        ast.parse(content)
    except SyntaxError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "The script contains a Python syntax error.",
                "line": exc.lineno,
                "column": exc.offset,
                "error": exc.msg,
            },
        ) from exc


def atomic_write(path: Path, content: str) -> None:
    """Write a file atomically so an interrupted save won't leave it half-written."""
    temporary_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=TESTS_DIR,
            prefix=".script-save-",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temporary_path = Path(temp_file.name)
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())

        os.replace(temporary_path, path)

    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to save script: {exc}",
        ) from exc

    finally:
        if temporary_path and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass


@router.get("")
def list_scripts():
    """List existing pytest files in the tests directory."""
    if not TESTS_DIR.is_dir():
        raise HTTPException(
            status_code=500,
            detail="The project tests directory does not exist.",
        )

    scripts = []

    for path in sorted(TESTS_DIR.glob("test_*.py")):
        if not path.is_file():
            continue

        try:
            content = read_script(path)
            tree = ast.parse(content, filename=path.name)

            test_functions = [
                node.name
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")
            ]

            scripts.append(
                {
                    "filename": path.name,
                    "path": f"tests/{path.name}",
                    "size_bytes": path.stat().st_size,
                    "test_count": len(test_functions),
                    "test_functions": test_functions,
                }
            )

        except (SyntaxError, OSError):
            # Keep the script visible even if it currently has syntax errors.
            scripts.append(
                {
                    "filename": path.name,
                    "path": f"tests/{path.name}",
                    "size_bytes": path.stat().st_size,
                    "test_count": None,
                    "test_functions": [],
                    "has_syntax_error": True,
                }
            )

    return {"scripts": scripts, "count": len(scripts)}


@router.get("/{filename}")
def get_script(filename: str):
    """Read one script for display or editing."""
    path = resolve_script(filename)

    if not path.is_file():
        raise HTTPException(status_code=404, detail="Script not found.")

    content = read_script(path)

    try:
        ast.parse(content, filename=filename)
        syntax_valid = True
        syntax_error = None
    except SyntaxError as exc:
        syntax_valid = False
        syntax_error = {
            "line": exc.lineno,
            "column": exc.offset,
            "message": exc.msg,
        }

    return {
        "filename": filename,
        "content": content,
        "syntax_valid": syntax_valid,
        "syntax_error": syntax_error,
    }


@router.post("", status_code=201)
def create_script(request: ScriptCreateRequest):
    """Create a new test script without overwriting existing files."""
    path = resolve_script(request.filename)

    if path.exists():
        raise HTTPException(
            status_code=409,
            detail="A script with this filename already exists.",
        )

    validate_python(request.content)

    # O_EXCL ensures this operation won't overwrite a file created concurrently.
    try:
        descriptor = os.open(
            str(path),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail="A script with this filename already exists.",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to create script: {exc}",
        ) from exc

    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as file:
            file.write(request.content)
            file.flush()
            os.fsync(file.fileno())
    except OSError as exc:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

        raise HTTPException(
            status_code=500,
            detail=f"Unable to write new script: {exc}",
        ) from exc

    return {
        "message": "Script created successfully.",
        "filename": request.filename,
        "path": f"tests/{request.filename}",
    }


@router.put("/{filename}")
def update_script(filename: str, request: ScriptUpdateRequest):
    """Update an existing script after validating its Python syntax."""
    path = resolve_script(filename)

    if not path.is_file():
        raise HTTPException(status_code=404, detail="Script not found.")

    validate_python(request.content)
    atomic_write(path, request.content)

    return {
        "message": "Script updated successfully.",
        "filename": filename,
        "path": f"tests/{filename}",
    }

#!/usr/bin/env python3
"""
Caveman Memory Compression Orchestrator

Usage:
    python scripts/compress.py <filepath>
"""

import os
import re
import subprocess
from pathlib import Path
from typing import List

OUTER_FENCE_REGEX = re.compile(
    r"\A\s*(`{3,}|~{3,})[^\n]*\n(.*)\n\1\s*\Z", re.DOTALL
)

SENSITIVE_BASENAME_REGEX = re.compile(
    r"(?ix)^("
    r"\.env(\..+)?"
    r"|\.netrc"
    r"|credentials(\..+)?"
    r"|secrets?(\..+)?"
    r"|passwords?(\..+)?"
    r"|id_(rsa|dsa|ecdsa|ed25519)(\.pub)?"
    r"|authorized_keys"
    r"|known_hosts"
    r"|.*\.(pem|key|p12|pfx|crt|cer|jks|keystore|asc|gpg)"
    r")$"
)

SENSITIVE_PATH_COMPONENTS = frozenset({".ssh", ".aws", ".gnupg", ".kube", ".docker"})

SENSITIVE_NAME_TOKENS = (
    "secret", "credential", "password", "passwd",
    "apikey", "accesskey", "token", "privatekey",
)


def is_sensitive_path(filepath: Path) -> bool:
    name = filepath.name
    if SENSITIVE_BASENAME_REGEX.match(name):
        return True
    lowered_parts = {p.lower() for p in filepath.parts}
    if lowered_parts & SENSITIVE_PATH_COMPONENTS:
        return True
    lower = re.sub(r"[_\-\s.]", "", name.lower())
    return any(tok in lower for tok in SENSITIVE_NAME_TOKENS)


def strip_llm_wrapper(text: str) -> str:
    m = OUTER_FENCE_REGEX.match(text)
    if m:
        return m.group(2)
    return text

from .detect import should_compress
from .validate import validate

MAX_RETRIES = 2


def call_claude(prompt: str) -> str:
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY not set")
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=api_key,
            base_url="https://integrate.api.nvidia.com/v1",
        )
        model = os.environ.get("CAVEMAN_MODEL", "nvidia/nemotron-3-super-120b-a12b")
        response = client.chat.completions.create(
            model=model,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
        return strip_llm_wrapper(response.choices[0].message.content.strip())
    except ImportError:
        raise RuntimeError("openai package required: pip install openai")


def build_compress_prompt(original: str) -> str:
    return f"""
Compress this markdown into caveman format.

STRICT RULES:
- Do NOT modify anything inside ``` code blocks
- Do NOT modify anything inside inline backticks
- Preserve ALL URLs exactly
- Preserve ALL headings exactly
- Preserve file paths and commands
- Return ONLY the compressed markdown body — do NOT wrap the entire output in a ```markdown fence or any other fence. Inner code blocks from the original stay as-is; do not add a new outer fence around the whole file.

Only compress natural language.

TEXT:
{original}
"""


def build_fix_prompt(original: str, compressed: str, errors: List[str]) -> str:
    errors_str = "\n".join(f"- {e}" for e in errors)
    return f"""You are fixing a caveman-compressed markdown file. Specific validation errors were found.

CRITICAL RULES:
- DO NOT recompress or rephrase the file
- ONLY fix the listed errors — leave everything else exactly as-is
- The ORIGINAL is provided as reference only (to restore missing content)
- Preserve caveman style in all untouched sections

ERRORS TO FIX:
{errors_str}

HOW TO FIX:
- Missing URL: find it in ORIGINAL, restore it exactly where it belongs in COMPRESSED
- Code block mismatch: find the exact code block in ORIGINAL, restore it in COMPRESSED
- Heading mismatch: restore the exact heading text from ORIGINAL into COMPRESSED
- Do not touch any section not mentioned in the errors

ORIGINAL (reference only):
{original}

COMPRESSED (fix this):
{compressed}

Return ONLY the fixed compressed file. No explanation.
"""


def compress_file(filepath: Path) -> bool:
    filepath = filepath.resolve()
    MAX_FILE_SIZE = 500_000
    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {filepath}")
    if filepath.stat().st_size > MAX_FILE_SIZE:
        raise ValueError(f"File too large to compress safely (max 500KB): {filepath}")

    if is_sensitive_path(filepath):
        raise ValueError(
            f"Refusing to compress {filepath}: filename looks sensitive "
            "(credentials, keys, secrets, or known private paths). "
            "Compression sends file contents to the Anthropic API. "
            "Rename the file if this is a false positive."
        )

    print(f"Processing: {filepath}")

    if not should_compress(filepath):
        print("Skipping (not natural language)")
        return False

    original_text = filepath.read_text(errors="ignore")
    backup_path = filepath.with_name(filepath.stem + ".original.md")

    if not original_text.strip():
        print("❌ Refusing to compress: file is empty or whitespace-only.")
        return False

    if backup_path.exists():
        print(f"⚠️ Backup file already exists: {backup_path}")
        print("The original backup may contain important content.")
        print("Aborting to prevent data loss. Please remove or rename the backup file if you want to proceed.")
        return False

    print("Compressing with Claude...")
    compressed = call_claude(build_compress_prompt(original_text))

    if compressed is None or not compressed.strip():
        print("❌ Compression aborted: Claude returned an empty response.")
        print("   Original file is untouched (no backup created).")
        return False

    if compressed.strip() == original_text.strip():
        print("❌ Compression aborted: output is identical to input.")
        print("   Likely causes: Claude refused, returned the prompt verbatim, or the file is")
        print("   already in caveman form. Original file is untouched (no backup created).")
        return False

    backup_path.write_text(original_text)
    backup_readback = backup_path.read_text(errors="ignore")
    if backup_readback != original_text:
        print(f"❌ Backup write verification failed: {backup_path}")
        print("   In-memory original differs from on-disk backup. Aborting before touching the input file.")
        try:
            backup_path.unlink()
        except OSError:
            pass
        return False
    filepath.write_text(compressed)

    for attempt in range(MAX_RETRIES):
        print(f"\nValidation attempt {attempt + 1}")

        result = validate(backup_path, filepath)

        if result.is_valid:
            print("Validation passed")
            break

        print("❌ Validation failed:")
        for err in result.errors:
            print(f"   - {err}")

        if attempt == MAX_RETRIES - 1:
            filepath.write_text(original_text)
            backup_path.unlink(missing_ok=True)
            print("❌ Failed after retries — original restored")
            return False

        print("Fixing with Claude...")
        compressed = call_claude(
            build_fix_prompt(original_text, compressed, result.errors)
        )
        filepath.write_text(compressed)

    return True

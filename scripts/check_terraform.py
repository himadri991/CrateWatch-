#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import hcl2

ROOT = Path(__file__).resolve().parents[1]
TF_DIR = ROOT / "infra" / "terraform"


def main() -> int:
    files = sorted(TF_DIR.glob("*.tf"))
    example = TF_DIR / "terraform.tfvars.example"
    if example.exists():
        files.append(example)

    if not files:
        print("No Terraform files found")
        return 1

    for path in files:
        with path.open(encoding="utf-8") as handle:
            try:
                hcl2.load(handle)
            except Exception as exc:
                print(f"{path.name}: parse error: {exc}")
                return 1
        print(f"{path.name}: parsed")

    print(f"HCL syntax check passed: {len(files)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())

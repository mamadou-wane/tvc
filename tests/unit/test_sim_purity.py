import ast
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SIM_ROOT = ROOT / "sim"
KERNEL_FILES = (
    "__init__.py",
    "types.py",
    "fixmath.py",
    "rng.py",
    "plant.py",
    "actuator.py",
    "sensor.py",
    "environment.py",
)

FORBIDDEN_IMPORT_ROOTS = {
    "asyncio",
    "cmath",
    "concurrent",
    "datetime",
    "glob",
    "http",
    "math",
    "multiprocessing",
    "os",
    "pathlib",
    "random",
    "selectors",
    "shutil",
    "socket",
    "subprocess",
    "tempfile",
    "threading",
    "time",
    "urllib",
}

FORBIDDEN_SIM_MODULES = {
    "sim.control_ref",
    "sim.episode",
    "sim.link",
    "sim.replay",
    "sim.run_sim",
    "sim.scenario",
    "sim.station",
}


def parse_module(filename):
    source_path = SIM_ROOT / filename
    if not source_path.is_file():
        raise AssertionError(f"missing required kernel module: {source_path}")
    return ast.parse(source_path.read_text(), filename=str(source_path))


def imported_names(tree):
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


class SimulationPurityTests(unittest.TestCase):
    def test_kernel_has_no_forbidden_runtime_dependencies(self):
        violations = []
        for filename in KERNEL_FILES:
            tree = parse_module(filename)
            for imported in imported_names(tree):
                root = imported.split(".", 1)[0]
                if root in FORBIDDEN_IMPORT_ROOTS:
                    violations.append((filename, imported, "forbidden runtime dependency"))
                elif imported == "ground" or imported.startswith("ground."):
                    violations.append((filename, imported, "wire or station dependency"))
                elif any(
                    imported == forbidden or imported.startswith(forbidden + ".")
                    for forbidden in FORBIDDEN_SIM_MODULES
                ):
                    violations.append((filename, imported, "later simulation layer"))
                elif root != "sim" and root not in sys.stdlib_module_names:
                    violations.append((filename, imported, "third-party dependency"))

            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id in {"open", "__import__"}:
                        violations.append((filename, node.func.id, "filesystem or dynamic import"))

        self.assertEqual(violations, [])

    def test_fixmath_uses_no_power_or_transcendental_call(self):
        tree = parse_module("fixmath.py")
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
                violations.append((node.lineno, "power"))
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    called = node.func.attr
                else:
                    called = ""
                if called in {"sin", "sinh", "asin"}:
                    violations.append((node.lineno, called))
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()

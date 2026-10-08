"""Architecture guards for the runtime-coordinator decomposition."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "custom_components" / "eybond_local" / "runtime"
COORDINATOR_PACKAGE = RUNTIME / "coordinator"
COORDINATOR = COORDINATOR_PACKAGE / "root.py"

MIXINS = {
    "lifecycle.py": "CoordinatorLifecycleMixin",
    "diagnostics.py": "CoordinatorDiagnosticsMixin",
    "startup.py": "CoordinatorStartupIdentityMixin",
    "cloud_tools.py": "CoordinatorCloudToolsMixin",
    "snapshot_projection.py": "CoordinatorSnapshotProjectionMixin",
    "support.py": "CoordinatorSupportMixin",
    "strategy.py": "CoordinatorStrategyTransitionMixin",
    "management.py": "CoordinatorManagementMixin",
    "management_projection.py": "CoordinatorManagementProjectionMixin",
    "network.py": "CoordinatorNetworkReconcileMixin",
    "entity_reload.py": "CoordinatorEntityReloadMixin",
    "operating_profile.py": "CoordinatorOperatingProfileMixin",
    "persistence.py": "CoordinatorPersistenceMixin",
    "runtime_profile.py": "CoordinatorRuntimeProfileMixin",
    "polling.py": "CoordinatorPollingMixin",
    "collector_profile.py": "CoordinatorCollectorProfileMixin",
    "control_projection.py": "CoordinatorControlProjectionMixin",
    "inverter_profile.py": "CoordinatorInverterProfileMixin",
    "device_registry.py": "CoordinatorDeviceRegistryMixin",
}

EXPECTED_MRO = [
    # The v0.3.0 code-quality branch groups the nineteen single-purpose mixins
    # into four cohesive composites. The invariant that matters is unchanged
    # and still enforced below: every lifecycle method has exactly one owner
    # (EXPECTED_METHOD_SET_SHA256), and the MRO stays explicit and short.
    #
    # The composites are named ...GroupMixin after their module. A composite that
    # reused its own leaf's name (polling_group.CoordinatorPollingMixin) shadowed
    # that leaf, leaving two distinct classes under one importable name.
    "CoordinatorCoreMixin",
    "CoordinatorPollingGroupMixin",
    "CoordinatorManagementGroupMixin",
    "CoordinatorIntegrationMixin",
    "DataUpdateCoordinator[RuntimeSnapshot]",
]

EXPECTED_METHOD_SET_SHA256 = (
    "c3eea8b76ef2ce10554898e607467b5c7615354e1e4c59a4b79900f1bc00cbfb"
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _class(path: Path, name: str) -> ast.ClassDef:
    return next(
        node
        for node in _tree(path).body
        if isinstance(node, ast.ClassDef) and node.name == name
    )


def _methods(node: ast.ClassDef) -> tuple[str, ...]:
    return tuple(
        child.name
        for child in node.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _module_level_classes(path: Path) -> set[str]:
    return {
        node.name
        for node in _tree(path).body
        if isinstance(node, ast.ClassDef)
    }


class CoordinatorCompositionBoundaryTests(unittest.TestCase):
    def test_composition_root_contains_only_constructor_logic(self) -> None:
        coordinator = _class(COORDINATOR, "EybondLocalCoordinator")
        self.assertEqual(_methods(coordinator), ("__init__",))
        self.assertLessEqual(len(COORDINATOR.read_text(encoding="utf-8").splitlines()), 400)

    def test_mro_is_explicit_and_stable(self) -> None:
        coordinator = _class(COORDINATOR, "EybondLocalCoordinator")
        bases = [
            base.id if isinstance(base, ast.Name) else ast.unparse(base)
            for base in coordinator.bases
        ]
        self.assertEqual(bases, EXPECTED_MRO)

    def test_every_lifecycle_method_has_exactly_one_owner(self) -> None:
        owners: dict[str, list[str]] = {}
        classes = [("root.py", _class(COORDINATOR, "EybondLocalCoordinator"))]
        classes.extend(
            (filename, _class(COORDINATOR_PACKAGE / filename, class_name))
            for filename, class_name in MIXINS.items()
        )
        for filename, lifecycle in classes:
            for method in _methods(lifecycle):
                owners.setdefault(method, []).append(filename)

        duplicates = {name: paths for name, paths in owners.items() if len(paths) != 1}
        self.assertEqual(duplicates, {})
        digest = hashlib.sha256("\n".join(sorted(owners)).encode()).hexdigest()
        self.assertEqual(len(owners), 293)
        self.assertEqual(owners["local_register_collection_availability"], ["support.py"])
        self.assertEqual(digest, EXPECTED_METHOD_SET_SHA256)

    def test_provider_neutral_cloud_evidence_surface_has_no_smartess_wrapper(self) -> None:
        methods = set()
        for filename, class_name in MIXINS.items():
            methods.update(
                _methods(_class(COORDINATOR_PACKAGE / filename, class_name))
            )
        self.assertNotIn("async_export_smartess_cloud_evidence", methods)
        self.assertNotIn("smartess_cloud_export_available", methods)
        self.assertIn("async_export_cloud_evidence", methods)
        self.assertIn("cloud_evidence_export_available", methods)
        self.assertIn("support_acquisition_readiness", methods)
        self.assertNotIn("device_info", methods)

    def test_no_class_name_is_defined_in_two_modules(self) -> None:
        # A composite that reuses one of its own leaf class names shadows that
        # leaf: `from .polling_group import CoordinatorPollingMixin` and
        # `from .polling import CoordinatorPollingMixin` would then name two
        # DIFFERENT classes, and whichever a caller imported would decide which
        # set of methods the coordinator has. Nothing else in this file catches
        # that -- the lifecycle-ownership check reads each leaf by an explicit
        # (module, class) pair, so a shadowing composite stays invisible to it.
        owners: dict[str, list[str]] = {}
        for path in sorted(COORDINATOR_PACKAGE.glob("*.py")):
            for name in _module_level_classes(path):
                owners.setdefault(name, []).append(path.name)
        duplicates = {
            name: paths for name, paths in owners.items() if len(paths) > 1
        }
        self.assertEqual(
            duplicates,
            {},
            "one class name must be defined in exactly one module "
            f"(rename the composite to ...GroupMixin): {duplicates}",
        )

    def test_no_class_lists_itself_as_a_base(self) -> None:
        # The exact signature of the shadowing bug: polling_group.py declared
        # `class CoordinatorPollingMixin(CoordinatorPollingMixin, ...)`, so the
        # composite's own name was also one of its base names. That resolves to
        # the leaf it imports, which is why it ran -- and it left two distinct
        # classes under one importable name. A class may never inherit itself.
        offenders: dict[str, list[str]] = {}
        for path in sorted(COORDINATOR_PACKAGE.glob("*.py")):
            for node in _tree(path).body:
                if not isinstance(node, ast.ClassDef):
                    continue
                base_names = [
                    base.id for base in node.bases if isinstance(base, ast.Name)
                ]
                if node.name in base_names:
                    offenders[f"{path.name}:{node.name}"] = base_names
        self.assertEqual(
            offenders,
            {},
            "a class must not appear in its own base list (rename the "
            f"composite to ...GroupMixin): {offenders}",
        )

    def test_composite_bases_resolve_to_their_leaf_modules(self) -> None:
        # Pins which module each composite's bases come from, so a future
        # composite cannot quietly inherit a sibling composite's methods.
        expected = {
            "polling_group.py": "CoordinatorPollingGroupMixin",
            "management_group.py": "CoordinatorManagementGroupMixin",
            "core.py": "CoordinatorCoreMixin",
            "integration.py": "CoordinatorIntegrationMixin",
        }
        for filename, class_name in expected.items():
            node = _class(COORDINATOR_PACKAGE / filename, class_name)
            base_names = [
                base.id for base in node.bases if isinstance(base, ast.Name)
            ]
            # Every base must be defined by some OTHER coordinator module.
            for base in base_names:
                owners = [
                    other.name
                    for other in sorted(COORDINATOR_PACKAGE.glob("*.py"))
                    if other.name != filename and base in _module_level_classes(other)
                ]
                self.assertTrue(
                    owners,
                    f"{filename}:{class_name} bases on {base}, which no other "
                    "coordinator module defines",
                )

    def test_mixins_have_no_constructor_or_coordinator_back_import(self) -> None:
        for filename, class_name in MIXINS.items():
            path = COORDINATOR_PACKAGE / filename
            self.assertNotIn("__init__", _methods(_class(path, class_name)), filename)
            imports = _imported_modules(path)
            self.assertFalse(
                any(module == "coordinator" or module.endswith(".coordinator") for module in imports),
                filename,
            )

    def test_one_class_owns_each_transaction_family(self) -> None:
        expected = {
            "async_start_proxy_capture": "cloud_tools.py",
            "async_start_shadow_learning": "cloud_tools.py",
            "_run_finalization_shielded": "cloud_tools.py",
            "async_run_connection_strategy_transition": "strategy.py",
            "_async_prepare_strategy_transition_management_session": (
                "strategy.py"
            ),
            "_apply_transition_commit": "strategy.py",
            "_collector_endpoint_operation": "management.py",
            "_async_update_data": "polling.py",
            "_async_update_data_with_runtime_lock": "polling.py",
        }
        actual: dict[str, str] = {}
        for filename, class_name in MIXINS.items():
            for method in _methods(_class(COORDINATOR_PACKAGE / filename, class_name)):
                if method in expected:
                    actual[method] = filename
        self.assertEqual(actual, expected)


class CoordinatorPureProjectionBoundaryTests(unittest.TestCase):
    def test_pure_projection_modules_do_not_import_ha_or_lifecycles(self) -> None:
        for filename in (
            "endpoint_projection.py",
            "poll_projection.py",
            "tooling_projection.py",
        ):
            imports = _imported_modules(COORDINATOR_PACKAGE / filename)
            self.assertFalse(any(module.startswith("homeassistant") for module in imports), filename)
            self.assertFalse(
                any(module.startswith("coordinator_") for module in imports),
                filename,
            )


if __name__ == "__main__":
    unittest.main()

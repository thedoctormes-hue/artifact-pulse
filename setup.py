from setuptools import setup, find_packages

setup(
    name="artifact-pulse",
    version="4.0.0",
    packages=find_packages(),
    py_modules=[
        "artifact_core", "artifact_aging", "artifact_changelog",
        "artifact_constraints", "artifact_graph", "artifact_health",
        "artifact_link_checker", "artifact_monitor", "artifact_provenance",
        "artifact_stats", "audit_report", "config_loader",
        "normalize_frontmatter", "search_artifacts", "__init__",
    ],
    install_requires=[
        "pyyaml>=6.0",
    ],
    entry_points={
        "console_scripts": [
            "artifact_health=artifact_health:main",
            "artifact_search=search_artifacts:main",
            "artifact_links=artifact_link_checker:main",
            "artifact_aging=artifact_aging:main",
            "artifact_stats=artifact_stats:main",
            "artifact_monitor=artifact_monitor:main",
            "artifact_provenance=artifact_provenance:main",
            "artifact_constraints=artifact_constraints:main",
            "artifact_graph=artifact_graph:main",
            "artifact_changelog=artifact_changelog:main",
            "artifact_audit=audit_report:main",
            "artifact_normalize=normalize_frontmatter:main",
        ],
    },
)

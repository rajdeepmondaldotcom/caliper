from __future__ import annotations

from caliper.models import Aggregate
from caliper.tui.screens.projects import _project_table_label


def test_project_table_label_shows_folder_name_for_full_path() -> None:
    project = Aggregate(
        key="/workspace/example-product",
        label="/workspace/example-product",
    )

    assert _project_table_label(project) == "example-product"


def test_project_table_label_keeps_non_path_label() -> None:
    project = Aggregate(key="Project Alpha", label="Project Alpha")

    assert _project_table_label(project) == "Project Alpha"


def test_project_table_label_falls_back_for_empty_label_and_key() -> None:
    project = Aggregate(key="", label="")

    assert _project_table_label(project) == "Unknown Project"


def test_project_table_label_truncates_after_shortening() -> None:
    long_name = "this-project-name-is-intentionally-long-enough-to-need-truncation"
    project = Aggregate(
        key=f"/tmp/{long_name}",
        label=f"/tmp/{long_name}",
    )

    assert _project_table_label(project) == long_name[:48]

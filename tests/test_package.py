def test_package_exposes_version() -> None:
    import zhanlu_worker

    assert zhanlu_worker.__version__ == "0.1.0"


def test_console_entry_point_loads() -> None:
    from importlib.metadata import entry_points

    scripts = entry_points(group="console_scripts", name="zhanlu-worker")

    assert len(scripts) == 1
    assert callable(next(iter(scripts)).load())

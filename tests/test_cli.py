from typer.testing import CliRunner

from brief.cli import app

runner = CliRunner()


def test_top_level_help_lists_product_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ["init", "source", "build", "publish", "serve", "runs", "doctor"]:
        assert command in result.stdout


def test_init_creates_valid_configuration(tmp_path) -> None:
    config = tmp_path / "brief.yaml"
    result = runner.invoke(app, ["init", "--config", str(config)], input="\n\n\n")
    assert result.exit_code == 0
    assert config.exists()
    assert "The Morning Brief" in config.read_text()


def test_doctor_reports_missing_config(tmp_path) -> None:
    result = runner.invoke(app, ["doctor", "--config", str(tmp_path / "missing.yaml")])
    assert result.exit_code == 1
    assert "configuration file not found" in result.stdout


def test_build_rejects_invalid_date(tmp_path) -> None:
    config = tmp_path / "brief.yaml"
    initialized = runner.invoke(app, ["init", "--config", str(config)], input="\n\n\n")
    assert initialized.exit_code == 0
    result = runner.invoke(app, ["build", "--config", str(config), "--date", "not-a-date"])
    assert result.exit_code == 1
    assert "--date must use YYYY-MM-DD format" in result.stdout

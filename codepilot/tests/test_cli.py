from pico import cli


def test_repl_cwd_switches_workspace(monkeypatch, tmp_path, capsys):
    original = tmp_path / "original"
    target = tmp_path / "target"
    original.mkdir()
    target.mkdir()
    (original / "README.md").write_text("original\n", encoding="utf-8")
    (target / "README.md").write_text("target\n", encoding="utf-8")

    agent = cli.build_agent(cli.build_arg_parser().parse_args(["--cwd", str(original)]))
    inputs = iter([f'/cwd "{target}"', "/exit"])

    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.setattr(cli, "build_agent", lambda args: agent)
    monkeypatch.setattr(cli, "build_welcome", lambda *args, **kwargs: "")

    assert cli.main([]) == 0
    assert agent.workspace.cwd == str(target.resolve())
    assert "workspace switched:" in capsys.readouterr().out
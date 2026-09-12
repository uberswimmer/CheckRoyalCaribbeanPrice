"""Latest-run report contracts. All inputs are fictional; no Royal requests."""
import logging
from pathlib import Path
from unittest.mock import Mock

import pytest
import CheckRoyalCaribbeanPrice as c


@pytest.fixture
def report_run(tmp_path, monkeypatch):
    logger = logging.getLogger()
    monkeypatch.setattr(logger, 'handlers', [])
    monkeypatch.setattr(logger, 'level', logging.INFO)
    settings = c.CruiseAppConfig(report_directory=str(tmp_path / 'public'))
    monkeypatch.setattr(c, 'config', settings)
    monkeypatch.setattr(c, 'main', Mock())
    return settings, Path(settings.report_directory)


def test_color_spacing_html_escape_and_plain_file_with_existing_log_filter(report_run, tmp_path):
    _, directory = report_run
    handler = logging.FileHandler(tmp_path / 'existing.log')
    handler.addFilter(c.StripAnsiFilter())
    logging.getLogger().addHandler(handler)
    def run():
        logging.info(c.BLUE + 'Heading' + c.RESET)
        logging.info(' ')
        logging.info(c.GREEN + '    Available <script>alert("x")</script> & more' + c.RESET)
    c.main.side_effect = run
    try:
        c.run_with_web_report()
    finally:
        handler.close()
    page = (directory / 'index.html').read_text()
    assert '<span class="blue">Heading</span>\n \n' in page
    assert '<span class="green">    Available &lt;script&gt;' in page
    assert '<script>' not in page and '\x1b' not in page
    assert 'Completed' in page and 'Started:' in page and 'Finished:' in page
    plain = (directory / 'report.txt').read_text()
    assert '    Available <script>' in plain and '\x1b' not in plain
    assert '\x1b' not in (tmp_path / 'existing.log').read_text()
    assert not any(isinstance(h, c.WebReport) for h in logging.getLogger().handlers)


@pytest.mark.parametrize('error', [c.AvailabilityUnknown('Check incomplete'), RuntimeError('Unexpected <error>'), SystemExit(1), KeyboardInterrupt()])
def test_failed_and_interrupted_runs_publish_status_and_preserve_exception(report_run, error):
    _, directory = report_run
    c.main.side_effect = error
    with pytest.raises(type(error)) as caught:
        c.run_with_web_report()
    assert caught.value is error
    page = (directory / 'index.html').read_text()
    assert '<strong>Failed</strong>' in page and 'Run stopped:' in page
    assert not any(isinstance(h, c.WebReport) for h in logging.getLogger().handlers)


def test_latest_run_replaces_previous_report_and_running_marker_is_visible(report_run):
    _, directory = report_run
    c.main.side_effect = lambda: logging.info('OLD RUN')
    c.run_with_web_report()
    def next_run():
        assert '<strong>Running</strong>' in (directory / 'index.html').read_text()
        logging.info('NEW RUN')
    c.main.side_effect = next_run
    c.run_with_web_report()
    page = (directory / 'index.html').read_text()
    assert 'NEW RUN' in page and 'OLD RUN' not in page


def test_calendar_publication_excludes_capture_and_preserves_unchanged_mtime(report_run, tmp_path):
    settings, directory = report_run
    source = tmp_path / 'calendar'
    source.mkdir()
    settings.calendar = c.CalendarSettings((), str(source))
    (source / 'cruises.ics').write_bytes(b'BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n')
    (source / 'calendar-data.json').write_text('{"private":"capture"}')
    c.run_with_web_report()
    feed = directory / 'cruises.ics'
    timestamp = feed.stat().st_mtime_ns
    assert set(p.name for p in directory.iterdir()) == {'cruises.ics', 'index.html', 'report.txt'}
    assert feed.stat().st_mode & 0o777 == 0o644
    c.run_with_web_report()
    assert feed.stat().st_mtime_ns == timestamp
    # A failed request may leave a previous calendar; keep serving it with a failed report.
    c.main.side_effect = c.CalendarError('Incomplete')
    with pytest.raises(c.CalendarError):
        c.run_with_web_report()
    assert feed.stat().st_mtime_ns == timestamp
    c.main.side_effect = None
    settings.calendar = None
    c.run_with_web_report()
    assert not feed.exists()


def test_report_capture_is_bounded(report_run, monkeypatch):
    _, directory = report_run
    monkeypatch.setattr(c.WebReport, 'MAX_CHARACTERS', 30)
    c.main.side_effect = lambda: [logging.info('x' * 20) for _ in range(100)]
    c.run_with_web_report()
    plain = (directory / 'report.txt').read_text()
    assert '[Report truncated;' in plain
    assert plain.count('x') == 29


def test_write_failure_is_report_error_not_missing_config_download(report_run):
    settings, directory = report_run
    directory.write_text('not a directory')
    with pytest.raises(c.ReportError):
        c.run_with_web_report()
    c.main.assert_not_called()
    assert not any(isinstance(h, c.WebReport) for h in logging.getLogger().handlers)


def test_disabled_report_does_not_write(report_run):
    settings, directory = report_run
    settings.report_directory = None
    c.run_with_web_report()
    c.main.assert_called_once()
    assert not directory.exists()


def test_apprise_test_does_not_replace_report(report_run):
    settings, directory = report_run
    settings.apprise_test = True
    c.run_with_web_report()
    assert not directory.exists()
    c.main.assert_called_once()


@pytest.mark.parametrize('value', [False, 42, [], {}, ' ', ''])
def test_report_config_rejects_invalid_paths(tmp_path, value):
    import yaml
    path = tmp_path / 'config.yaml'
    path.write_text(yaml.safe_dump({'reportDirectory': value}))
    with pytest.raises(ValueError, match='reportDirectory'):
        c.load_config_objects(str(path))


def test_calendar_copy_failure_still_writes_failed_report(report_run, tmp_path):
    settings, directory = report_run
    source = tmp_path / 'calendar'
    source.mkdir()
    (source / 'cruises.ics').mkdir()  # Invalid source exercises a real IO failure.
    settings.calendar = c.CalendarSettings((), str(source))
    with pytest.raises(c.ReportError):
        c.run_with_web_report()
    page = (directory / 'index.html').read_text()
    assert '<strong>Failed</strong>' in page and 'Cannot publish calendar feed' in page


def test_validation_does_not_generate_report(report_run, monkeypatch):
    settings, directory = report_run
    monkeypatch.setattr(c, 'get_config_path', Mock(return_value='unused.yaml'))
    monkeypatch.setattr(c, 'load_config_objects', Mock(return_value=settings))
    monkeypatch.setattr(c, 'log', Mock())
    monkeypatch.setattr(c, 'VALIDATE_CONFIG_ONLY', True, raising=False)
    with pytest.raises(SystemExit) as caught:
        c.cli()
    assert caught.value.code == 0
    assert not directory.exists()
    c.main.assert_not_called()

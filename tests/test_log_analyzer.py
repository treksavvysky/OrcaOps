"""Tests for LogAnalyzer regex-based log analysis."""

from orcaops.log_analyzer import LogAnalyzer
from orcaops.schemas import StepResult, RunRecord, JobStatus, LogAnalysis


def _step(stdout="", stderr="", exit_code=0):
    return StepResult(
        command="test", exit_code=exit_code,
        stdout=stdout, stderr=stderr, duration_seconds=1.0,
    )


class TestErrorDetection:
    def test_detect_error_in_stderr(self):
        analyzer = LogAnalyzer()
        result = analyzer.analyze_step(_step(stderr="Error: file not found"))
        assert result.error_count == 1
        assert result.first_error == "Error: file not found"
        assert len(result.error_lines) == 1

    def test_detect_exception(self):
        analyzer = LogAnalyzer()
        result = analyzer.analyze_step(_step(stderr="ValueError: invalid literal"))
        # "ValueError" doesn't match since it needs "exception:" pattern
        # But "Exception:" would match
        result2 = analyzer.analyze_step(_step(stderr="Exception: something broke"))
        assert result2.error_count == 1

    def test_detect_failed_pattern(self):
        analyzer = LogAnalyzer()
        result = analyzer.analyze_step(_step(stdout="FAILED: test_foo"))
        assert result.error_count == 1

    def test_detect_exit_code_pattern(self):
        analyzer = LogAnalyzer()
        result = analyzer.analyze_step(_step(stderr="Process exit code 1"))
        assert result.error_count == 1

    def test_detect_panic(self):
        analyzer = LogAnalyzer()
        result = analyzer.analyze_step(_step(stderr="panic: runtime error"))
        assert result.error_count == 1


class TestWarningDetection:
    def test_detect_warning(self):
        analyzer = LogAnalyzer()
        result = analyzer.analyze_step(_step(stdout="WARNING: disk space low"))
        assert result.warning_count == 1
        assert result.error_count == 0

    def test_detect_deprecated(self):
        analyzer = LogAnalyzer()
        result = analyzer.analyze_step(_step(stdout="This function is deprecated"))
        assert result.warning_count == 1

    def test_error_not_counted_as_warning(self):
        analyzer = LogAnalyzer()
        result = analyzer.analyze_step(_step(stderr="Error: bad\nWarning: minor"))
        assert result.error_count == 1
        assert result.warning_count == 1


class TestStackTraceDetection:
    def test_python_traceback(self):
        analyzer = LogAnalyzer()
        output = (
            "Traceback (most recent call last):\n"
            "  File \"test.py\", line 10, in main\n"
            "    raise ValueError(\"bad\")\n"
            "ValueError: bad\n"
        )
        result = analyzer.analyze_step(_step(stderr=output))
        assert len(result.stack_traces) == 1
        assert "Traceback" in result.stack_traces[0]
        assert "File" in result.stack_traces[0]

    def test_node_stack_trace(self):
        analyzer = LogAnalyzer()
        output = (
            "Error: Cannot find module 'foo'\n"
            "    at Function.resolve (module.js:470:15)\n"
            "    at require (module.js:377:17)\n"
        )
        result = analyzer.analyze_step(_step(stderr=output))
        assert len(result.stack_traces) >= 1

    def test_go_goroutine(self):
        analyzer = LogAnalyzer()
        output = "goroutine 1 [running]:\nmain.main()\n  /app/main.go:10\n"
        result = analyzer.analyze_step(_step(stderr=output))
        assert len(result.stack_traces) >= 1


class TestCleanOutput:
    def test_no_errors_in_clean_output(self):
        analyzer = LogAnalyzer()
        result = analyzer.analyze_step(_step(stdout="hello world\nall good"))
        assert result.error_count == 0
        assert result.warning_count == 0
        assert result.first_error is None
        assert result.stack_traces == []
        assert result.error_lines == []


class TestRecordAggregation:
    def test_aggregate_across_steps(self):
        analyzer = LogAnalyzer()
        record = RunRecord(
            job_id="test", status=JobStatus.FAILED,
            steps=[
                _step(stderr="Error: first problem"),
                _step(stdout="all good"),
                _step(stderr="Error: second problem\nError: third problem"),
            ],
        )
        result = analyzer.analyze_record(record)
        assert result.error_count == 3
        assert result.first_error == "Error: first problem"

    def test_empty_record(self):
        analyzer = LogAnalyzer()
        record = RunRecord(job_id="test", status=JobStatus.SUCCESS, steps=[])
        result = analyzer.analyze_record(record)
        assert result.error_count == 0
        assert result.first_error is None


class TestCaps:
    def test_error_lines_capped_at_20(self):
        analyzer = LogAnalyzer()
        lines = "\n".join(f"Error: problem {i}" for i in range(30))
        result = analyzer.analyze_step(_step(stderr=lines))
        assert len(result.error_lines) == 20
        assert result.error_count == 30

    def test_stack_traces_capped_at_5(self):
        analyzer = LogAnalyzer()
        lines = ""
        for i in range(8):
            lines += f"Traceback (most recent call last):\n  File \"t.py\", line {i}\n\n"
        result = analyzer.analyze_step(_step(stderr=lines))
        assert len(result.stack_traces) == 5

    def test_error_line_truncated_at_200_chars(self):
        analyzer = LogAnalyzer()
        long_error = "Error: " + "x" * 300
        result = analyzer.analyze_step(_step(stderr=long_error))
        assert len(result.error_lines[0]) == 200

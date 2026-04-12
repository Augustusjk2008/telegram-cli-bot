from bot.handlers.tui_server import PtyWrapper


class _FakeWinptyProcess:
    def __init__(self):
        self.read_sizes = []

    def read(self, size=1024):
        self.read_sizes.append(size)
        return "prompt> "


def test_pty_wrapper_reads_winpty_output_with_size_argument():
    process = _FakeWinptyProcess()
    wrapper = PtyWrapper(process, is_pty=True)

    result = wrapper.read(timeout=200)

    assert result == "prompt> "
    assert process.read_sizes == [4096]

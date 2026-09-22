import logging
from PySide6.QtCore import QObject, QThread, Signal, QTimer
from PySide6.QtWidgets import QPushButton

logger = logging.getLogger(__name__)

# Maintain strong references to active background threads so Python GC never destroys them mid-execution
_ACTIVE_ASYNC_THREADS = set()


class SafeAsyncThread(QThread):
    finished_data = Signal(object)
    failed = Signal(str)

    def __init__(self, task_fn, parent=None):
        super().__init__(parent)
        self.task_fn = task_fn

    def run(self):
        try:
            result = self.task_fn()
            self.finished_data.emit(result)
        except Exception as exc:
            logger.exception(f'Error in async thread: {exc}')
            self.failed.emit(str(exc))


def run_async_task(task_fn, on_finished, on_error=None, parent=None):
    """
    Run a task in a dedicated background QThread and safely deliver the result 
    back to the Qt main thread via signals.
    """
    thread = SafeAsyncThread(task_fn, parent)
    _ACTIVE_ASYNC_THREADS.add(thread)

    thread.finished_data.connect(on_finished)
    if on_error:
        thread.failed.connect(on_error)

    def cleanup():
        _ACTIVE_ASYNC_THREADS.discard(thread)

    thread.finished.connect(cleanup)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread

def animate_refresh_button(button: QPushButton, loading: bool, default_text: str = '↻ Refresh'):
    if not button:
        return
    if loading:
        button.setEnabled(False)
        button.setText('⏳ Updating...')
    else:
        button.setEnabled(True)
        button.setText('✓ Updated')
        QTimer.singleShot(1600, lambda: button.setText(default_text) if button else None)

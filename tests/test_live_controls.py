from test_ui_recording import app,ui
import time
w=ui.MainWindow();w.show()
def until(predicate):
    deadline=time.monotonic()+8
    while not predicate() and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
    assert predicate()
until(lambda:not w.busy)
w._toggle_preview()
until(lambda:not w.video.image.isNull())
pid=w.preview.process.processId()
w.request('apply',['brightness',42])
until(lambda:not w.busy)
assert w.preview.running and w.preview.process.processId()==pid
w.request('snapshot');until(lambda:not w.busy)
assert w.preview.process.processId()==pid
w.request('apply',['sleep',1]);until(lambda:not w.busy)
assert not w.preview_wanted and not w.preview.running
w.close();app.processEvents()
assert not w.thread.isRunning()
print('PASS ordinary apply/read preserve live capture PID; sleep stops capture without restart')

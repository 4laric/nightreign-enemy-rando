"""End-to-end GUI smoke test.

Runs the shipped GUI under the local Xvfb display:
  1. Starts from fresh-install state (.4laric_paths.json deleted).
  2. Schedules a series of programmatic actions on the Tk event loop
     to simulate the click-path a real user takes:
       a. Wizard appears → click Skip to dismiss.
       b. Main GUI loads → toggle MMV checkbox if present (exercises
          the line 6058 encoding code path).
       c. Click Randomize (with empty/invalid paths — we just want
          to see if the call site fires without AttributeError; the
          validation will safely reject the run).
  3. Captures any exceptions Tk raises into a list via the
     `report_callback_exception` hook. AttributeError, codec errors,
     and similar GUI-thread exceptions all funnel through this hook.
  4. Tears down after a timeout. Final assertion: zero unexpected
     exceptions caught.

Run via:
  rm -f /path/to/repo/.4laric_paths.json
  DISPLAY=:99 python3 /tmp/gui_smoke.py /path/to/extracted-zip

Exit 0 = clean (no GUI exceptions). Non-zero = something fired.
"""
import sys
import os
import time
import traceback


def run_smoke(repo_root):
    """Returns a list of (label, traceback_text) tuples for each
    unexpected exception caught during the smoke sequence."""
    print(f"[smoke] start, repo={repo_root}", flush=True)
    sys.path.insert(0, repo_root)
    os.chdir(repo_root)

    # Sanity: fresh-install state
    paths_file = os.path.join(repo_root, '.4laric_paths.json')
    assert not os.path.exists(paths_file), (
        f"Smoke test requires fresh-install state — delete {paths_file}")

    import tkinter as tk
    import oops_rando_gui

    captured = []

    # Hook every Tk callback exception into our list. Without this hook
    # they'd just print to stderr and the test wouldn't know they happened.
    original_report = tk.Tk.report_callback_exception
    def report(self, exc, val, tb):
        captured.append((
            f"{exc.__name__}: {val}",
            ''.join(traceback.format_exception(exc, val, tb))))
        original_report(self, exc, val, tb)
    tk.Tk.report_callback_exception = report

    # Mock modal dialogs to prevent them from blocking the event loop.
    # Real users see them; smoke test just records the call.
    dialog_calls = []
    import tkinter.messagebox as mb
    def fake_showerror(*a, **kw):
        dialog_calls.append(('showerror', a, kw))
    def fake_showinfo(*a, **kw):
        dialog_calls.append(('showinfo', a, kw))
    def fake_showwarning(*a, **kw):
        dialog_calls.append(('showwarning', a, kw))
    def fake_askyesno(*a, **kw):
        dialog_calls.append(('askyesno', a, kw))
        return False  # cancel everything by default
    def fake_askokcancel(*a, **kw):
        dialog_calls.append(('askokcancel', a, kw))
        return False
    mb.showerror = fake_showerror
    mb.showinfo = fake_showinfo
    mb.showwarning = fake_showwarning
    mb.askyesno = fake_askyesno
    mb.askokcancel = fake_askokcancel
    # Also patch the module-level reference oops_rando_gui imported
    oops_rando_gui.messagebox.showerror = fake_showerror
    oops_rando_gui.messagebox.showinfo = fake_showinfo
    oops_rando_gui.messagebox.showwarning = fake_showwarning
    oops_rando_gui.messagebox.askyesno = fake_askyesno
    oops_rando_gui.messagebox.askokcancel = fake_askokcancel
    print("[smoke] modal dialogs mocked", flush=True)

    # We need to run main() in a way that lets us inject events. Easiest:
    # manually replicate what main() does, then schedule our action
    # sequence via root.after() before entering mainloop.
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--setup', action='store_true')
    args, _ = parser.parse_known_args([])

    root = tk.Tk()
    try:
        from tkinter import ttk
        s = ttk.Style()
        if 'clam' in s.theme_names(): s.theme_use('clam')
    except Exception: pass

    saved = oops_rando_gui._load_saved_paths()
    assert saved == {}, f"saved paths leaked into smoke: {saved}"

    # Reach into module to find wizard symbols
    FirstLaunchWizard = oops_rando_gui.FirstLaunchWizard
    SplashWindow = oops_rando_gui.SplashWindow
    RandoGUI = oops_rando_gui.RandoGUI

    # --- Wizard path ---
    print("[smoke] withdrawing root", flush=True)
    root.withdraw()
    wizard_done = []

    def click_wizard_skip():
        """Find and trigger the Skip link on the wizard."""
        print("[smoke] click_wizard_skip firing", flush=True)
        try:
            wiz = wizard_ref[0]
            wiz._on_close()
            wizard_done.append('skipped')
        except Exception as e:
            captured.append(('wizard_skip_failed', traceback.format_exc()))

    wizard_ref = [None]
    try:
        print("[smoke] constructing wizard", flush=True)
        wiz = FirstLaunchWizard(root, initial_config=saved)
        wizard_ref[0] = wiz
        print("[smoke] wizard constructed, scheduling skip in 500ms", flush=True)
        root.after(500, click_wizard_skip)
        print("[smoke] entering wait_window", flush=True)
        root.wait_window(wiz.top)
        print("[smoke] wait_window returned", flush=True)
    except Exception:
        captured.append(('wizard_construction', traceback.format_exc()))
    finally:
        root.deiconify()

    if not wizard_done:
        captured.append(('wizard_never_skipped',
                         'after(500, click_wizard_skip) never fired'))

    # --- Main GUI path ---
    print("[smoke] constructing splash + RandoGUI", flush=True)
    splash = SplashWindow(root)
    try:
        gui = RandoGUI(root, progress_callback=splash.update_status)
        print("[smoke] RandoGUI constructed", flush=True)
    except Exception:
        print("[smoke] RandoGUI construction FAILED", flush=True)
        captured.append(('main_gui_construction', traceback.format_exc()))
        splash.close()
        root.destroy()
        return captured
    splash.close()
    print("[smoke] splash closed, scheduling actions", flush=True)

    # Schedule actions: toggle MMV (if it exists), click Randomize,
    # then quit after a short settle period.
    actions_done = []

    def toggle_mmv():
        print("[smoke] toggle_mmv firing", flush=True)
        try:
            if hasattr(gui, 'mmv_enabled_var'):
                current = gui.mmv_enabled_var.get()
                gui.mmv_enabled_var.set(not current)
                gui.mmv_enabled_var.set(current)
                print(f"[smoke]   mmv toggled (was {current})", flush=True)
            else:
                print(f"[smoke]   mmv_enabled_var attr not found on gui", flush=True)
            actions_done.append('mmv_toggle')
        except Exception:
            captured.append(('mmv_toggle', traceback.format_exc()))

    def click_randomize():
        print("[smoke] click_randomize firing", flush=True)
        try:
            gui._run_shuffle()
            print("[smoke]   _run_shuffle returned without raising", flush=True)
            actions_done.append('randomize_clicked')
        except Exception:
            print("[smoke]   _run_shuffle RAISED (captured)", flush=True)
            captured.append(('randomize_click', traceback.format_exc()))

    def teardown():
        print("[smoke] teardown firing", flush=True)
        try:
            root.quit()
            actions_done.append('teardown')
        except Exception:
            pass

    root.after(200, toggle_mmv)
    root.after(400, click_randomize)
    # Randomize spawns a thread for the actual shuffle. Give it 2s
    # to either complete or hit validation errors before tearing down.
    root.after(2400, teardown)

    root.mainloop()
    try: root.destroy()
    except Exception: pass

    if 'mmv_toggle' not in actions_done:
        captured.append(('mmv_toggle_never_ran', 'after(200) never fired'))
    if 'randomize_clicked' not in actions_done:
        captured.append(('randomize_never_clicked', 'after(400) never fired'))

    # Annotate any dialog calls so the report shows what would have
    # popped up if a real user were watching.
    print(f"[smoke] dialog_calls: {len(dialog_calls)}", flush=True)
    for kind, args, kwargs in dialog_calls:
        msg = args[1] if len(args) >= 2 else args[0] if args else '?'
        print(f"  [{kind}] {msg!r:.150}", flush=True)

    return captured


def main():
    repo_root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    captured = run_smoke(repo_root)
    print(f"[smoke] run_smoke returned, captured={len(captured)} item(s)", flush=True)
    if captured:
        print(f"\n!!! SMOKE FAILED — {len(captured)} unexpected exception(s):\n", flush=True)
        for label, tb_text in captured:
            print(f"  [{label}]", flush=True)
            for line in tb_text.splitlines():
                print(f"    {line}", flush=True)
            print(flush=True)
        sys.exit(1)
    print("\n✓ SMOKE PASSED — no unexpected GUI exceptions", flush=True)
    sys.exit(0)


if __name__ == '__main__':
    main()

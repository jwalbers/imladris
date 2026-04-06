"""
modality_console.py — Imladris Modality Console

A wxPython control panel that gives a radiology technologist a realistic
interface for the Orthanc + Python-sidecar DICOM modality simulator.

Workflow:
  1.  Refresh Worklist  → C-FIND SCU queries OpenMRS MWL
  2.  Select a patient  → detail panel populates
  3.  Acquire & Send    → Orthanc matches + C-STOREs to Cloud PACS

Run:
  python modality_console.py

Environment variables (all optional, sensible defaults for local dev):
  ORTHANC_URL     http://localhost:8042
  MWL_HOST        localhost
  MWL_PORT        4242
  MODALITY_AET    MODALITY_SIM
  CLOUD_PACS_AE   CLOUD_PACS
"""

import threading
from datetime import datetime

import wx
import wx.lib.scrolledpanel as scrolled

import dicom_client as dc


# ── Colours & fonts used throughout ──────────────────────────────────

_GREEN  = wx.Colour(0, 160, 60)
_RED    = wx.Colour(200, 30, 30)
_AMBER  = wx.Colour(200, 130, 0)
_GREY   = wx.Colour(120, 120, 120)
_MONO   = wx.Font(9, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
_BOLD14 = wx.Font(14, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
_BOLD11 = wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)


# ── Status indicator widget ───────────────────────────────────────────

class StatusLight(wx.Panel):
    """A small coloured dot + label indicating connection state."""

    UNKNOWN = ("●  {label}: Unknown",  _GREY)
    OK      = ("●  {label}: Connected", _GREEN)
    ERROR   = ("●  {label}: Unreachable", _RED)
    BUSY    = ("●  {label}: Querying…",   _AMBER)

    def __init__(self, parent, label: str):
        super().__init__(parent)
        self._label = label
        self._text = wx.StaticText(self, label=f"●  {label}: Unknown")
        self._text.SetForegroundColour(_GREY)
        s = wx.BoxSizer()
        s.Add(self._text, 0, wx.ALL, 0)
        self.SetSizer(s)

    def set_state(self, state: tuple):
        template, colour = state
        wx.CallAfter(self._text.SetLabel, template.format(label=self._label))
        wx.CallAfter(self._text.SetForegroundColour, colour)
        wx.CallAfter(self.Layout)


# ── Main frame ────────────────────────────────────────────────────────

class ModalityConsoleFrame(wx.Frame):

    def __init__(self):
        super().__init__(
            parent=None,
            title="Imladris Modality Console  —  AE: MODALITY_SIM",
            size=(1020, 720),
            style=wx.DEFAULT_FRAME_STYLE,
        )
        self._worklist: list[dc.WorklistEntry] = []
        self._selected: dc.WorklistEntry | None = None

        self._build_ui()
        self.Centre()
        self.Show()

        # Kick off connection checks in background
        threading.Thread(target=self._check_connections, daemon=True).start()

    # ── UI construction ───────────────────────────────────────────────

    def _build_ui(self):
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)

        root.Add(self._make_header(panel),     0, wx.EXPAND | wx.ALL, 10)
        root.Add(self._make_status_bar(panel), 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(wx.StaticLine(panel),         0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        root.Add(self._make_worklist(panel),   1, wx.EXPAND | wx.ALL, 10)
        root.Add(self._make_detail(panel),     0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(self._make_buttons(panel),    0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        root.Add(wx.StaticLine(panel),         0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        root.Add(self._make_log(panel),        0, wx.EXPAND | wx.ALL, 10)

        panel.SetSizer(root)

    def _make_header(self, parent):
        sizer = wx.BoxSizer(wx.HORIZONTAL)

        title = wx.StaticText(parent, label="Imladris Modality Console")
        title.SetFont(_BOLD14)

        subtitle = wx.StaticText(parent, label="CT / CXR Simulator  |  MDR-TB Virtual Integration Lab")
        subtitle.SetForegroundColour(_GREY)

        sizer.Add(title,    0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 16)
        sizer.Add(subtitle, 0, wx.ALIGN_CENTER_VERTICAL)
        return sizer

    def _make_status_bar(self, parent):
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._sl_mwl    = StatusLight(parent, "OpenMRS MWL")
        self._sl_orthanc = StatusLight(parent, "Orthanc")
        self._sl_pacs   = StatusLight(parent, "Cloud PACS")
        sizer.Add(self._sl_mwl,    0, wx.RIGHT, 24)
        sizer.Add(self._sl_orthanc, 0, wx.RIGHT, 24)
        sizer.Add(self._sl_pacs,   0)
        return sizer

    def _make_worklist(self, parent):
        box  = wx.StaticBox(parent, label="Modality Worklist  —  Scheduled Exams")
        box.SetFont(_BOLD11)
        sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        self._list = wx.ListCtrl(
            parent,
            style=wx.LC_REPORT | wx.BORDER_SUNKEN | wx.LC_SINGLE_SEL | wx.LC_HRULES,
        )
        cols = [
            ("#",           40),
            ("Patient Name", 200),
            ("Patient ID",  110),
            ("DOB",          90),
            ("Sex",          45),
            ("Modality",     75),
            ("Study Description", 220),
            ("Accession #",  130),
            ("Scheduled",    100),
        ]
        for i, (name, w) in enumerate(cols):
            self._list.InsertColumn(i, name, width=w)

        self._list.Bind(wx.EVT_LIST_ITEM_SELECTED,   self._on_select)
        self._list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self._on_deselect)

        sizer.Add(self._list, 1, wx.EXPAND | wx.ALL, 6)
        return sizer

    def _make_detail(self, parent):
        box   = wx.StaticBox(parent, label="Selected Patient")
        sizer = wx.StaticBoxSizer(box, wx.HORIZONTAL)
        self._detail = wx.StaticText(parent, label="No patient selected.")
        sizer.Add(self._detail, 1, wx.ALL, 8)
        return sizer

    def _make_buttons(self, parent):
        sizer = wx.BoxSizer(wx.HORIZONTAL)

        self._btn_refresh = wx.Button(parent, label="  Refresh Worklist  ")
        self._btn_acquire = wx.Button(parent, label="  Acquire && Send to PACS  ")
        self._btn_clear   = wx.Button(parent, label="  Clear  ")

        self._btn_acquire.SetFont(
            wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        )
        self._btn_acquire.Enable(False)

        self._btn_refresh.Bind(wx.EVT_BUTTON, self._on_refresh)
        self._btn_acquire.Bind(wx.EVT_BUTTON, self._on_acquire)
        self._btn_clear.Bind(wx.EVT_BUTTON,   self._on_clear)

        sizer.Add(self._btn_refresh, 0, wx.RIGHT, 8)
        sizer.Add(self._btn_acquire, 0, wx.RIGHT, 8)
        sizer.AddStretchSpacer()
        sizer.Add(self._btn_clear, 0)
        return sizer

    def _make_log(self, parent):
        box   = wx.StaticBox(parent, label="Activity Log")
        sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        self._log = wx.TextCtrl(
            parent,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_SUNKEN,
        )
        self._log.SetFont(_MONO)
        self._log.SetMinSize((-1, 110))

        sizer.Add(self._log, 1, wx.EXPAND | wx.ALL, 6)
        return sizer

    # ── Logging ───────────────────────────────────────────────────────

    def _write_log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        wx.CallAfter(self._log.AppendText, f"[{ts}]  {msg}\n")

    # ── Connection checks (background thread) ─────────────────────────

    def _check_connections(self):
        # Check Orthanc
        try:
            info = dc.check_orthanc()
            ver  = info.get("Version", "?")
            self._sl_orthanc.set_state(StatusLight.OK)
            self._write_log(f"Orthanc connected  (version {ver})")
        except Exception as e:
            self._sl_orthanc.set_state(StatusLight.ERROR)
            self._write_log(f"Orthanc unreachable: {e}")

        # MWL and PACS status update lazily (on first use)
        self._sl_mwl.set_state(StatusLight.UNKNOWN)
        self._sl_pacs.set_state(StatusLight.UNKNOWN)
        self._write_log("Ready.  Click 'Refresh Worklist' to query OpenMRS MWL.")

    # ── Worklist refresh ──────────────────────────────────────────────

    def _on_refresh(self, _event):
        self._btn_refresh.Enable(False)
        self._sl_mwl.set_state(StatusLight.BUSY)
        self._write_log("Querying OpenMRS MWL (C-FIND SCU) …")
        threading.Thread(target=self._fetch_worklist, daemon=True).start()

    def _fetch_worklist(self):
        try:
            entries = dc.query_mwl()
            wx.CallAfter(self._populate_list, entries)
            self._sl_mwl.set_state(StatusLight.OK)
            self._write_log(f"Worklist refreshed — {len(entries)} scheduled exam(s).")
        except Exception as e:
            self._sl_mwl.set_state(StatusLight.ERROR)
            self._write_log(f"MWL query failed: {e}")
        finally:
            wx.CallAfter(self._btn_refresh.Enable, True)

    def _populate_list(self, entries: list[dc.WorklistEntry]):
        self._list.DeleteAllItems()
        self._worklist = entries
        self._selected = None
        self._detail.SetLabel("No patient selected.")
        self._btn_acquire.Enable(False)

        for i, e in enumerate(entries):
            row = self._list.InsertItem(i, str(i + 1))
            self._list.SetItem(row, 1, e.patient_name)
            self._list.SetItem(row, 2, e.patient_id)
            self._list.SetItem(row, 3, e.dob)
            self._list.SetItem(row, 4, e.sex)
            self._list.SetItem(row, 5, e.modality)
            self._list.SetItem(row, 6, e.study_desc)
            self._list.SetItem(row, 7, e.accession)
            self._list.SetItem(row, 8, e.scheduled_date)

    # ── Patient selection ─────────────────────────────────────────────

    def _on_select(self, event):
        idx = event.GetIndex()
        if 0 <= idx < len(self._worklist):
            self._selected = self._worklist[idx]
            self._detail.SetLabel(self._selected.detail_string())
            self._btn_acquire.Enable(True)

    def _on_deselect(self, _event):
        self._selected = None
        self._detail.SetLabel("No patient selected.")
        self._btn_acquire.Enable(False)

    def _on_clear(self, _event):
        first = self._list.GetFirstSelected()
        if first != -1:
            self._list.Select(first, on=False)

    # ── Acquisition ───────────────────────────────────────────────────

    def _on_acquire(self, _event):
        if not self._selected:
            return
        entry = self._selected
        self._btn_acquire.Enable(False)
        self._btn_refresh.Enable(False)
        self._write_log(f"Acquiring: {entry.patient_name}  ({entry.patient_id})  —  {entry.study_desc} …")
        threading.Thread(target=self._do_acquire, args=(entry,), daemon=True).start()

    def _do_acquire(self, entry: dc.WorklistEntry):
        try:
            # Step 1: match to a TB study in Orthanc
            study_uid = dc.match_tb_study(entry.patient_id, entry.modality)
            if not study_uid:
                self._write_log(
                    f"No matching study in Orthanc for "
                    f"PatientID={entry.patient_id} Modality={entry.modality}"
                )
                return

            self._write_log(f"Matched Orthanc study UID: {study_uid}")
            self._write_log(f"Sending to Cloud PACS ({dc.CLOUD_PACS_AE}) …")

            # Step 2: trigger Orthanc C-STORE to Cloud PACS
            dc.send_study_to_pacs(study_uid)

            self._sl_pacs.set_state(StatusLight.OK)
            self._write_log(
                f"✓  Sent successfully —  "
                f"Patient: {entry.patient_name}   "
                f"Accession: {entry.accession}"
            )
            wx.CallAfter(self._remove_entry, entry)

        except Exception as ex:
            self._sl_pacs.set_state(StatusLight.ERROR)
            self._write_log(f"✗  Acquisition failed: {ex}")
        finally:
            wx.CallAfter(self._btn_refresh.Enable, True)
            wx.CallAfter(self._btn_acquire.Enable, bool(self._selected))

    def _remove_entry(self, entry: dc.WorklistEntry):
        """Remove a successfully sent entry from the worklist."""
        for i, e in enumerate(self._worklist):
            if e.accession == entry.accession and e.patient_id == entry.patient_id:
                self._list.DeleteItem(i)
                self._worklist.pop(i)
                # Re-number remaining rows
                for j in range(i, self._list.GetItemCount()):
                    self._list.SetItem(j, 0, str(j + 1))
                break
        self._selected = None
        self._detail.SetLabel("No patient selected.")
        self._btn_acquire.Enable(False)


# ── Entry point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    app = wx.App(False)
    ModalityConsoleFrame()
    app.MainLoop()

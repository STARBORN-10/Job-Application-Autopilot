import React, { useEffect, useRef, useState } from 'react';
import { ChevronDown, Download, FileSpreadsheet, FileText, Table } from 'lucide-react';
import { downloadExport } from '../api';
import { useToast } from '../context/contexts';
import { Spinner } from './Feedback';

const FORMATS = [
  { key: 'csv', label: 'CSV (.csv)', hint: 'Plain table for any spreadsheet app', Icon: Table },
  { key: 'xlsx', label: 'Excel (.xlsx)', hint: 'Formatted workbook', Icon: FileSpreadsheet },
  { key: 'pdf', label: 'PDF report (.pdf)', hint: 'Readable table to print or share', Icon: FileText },
];

// One "Export" button with a format menu. `filters` (status, min_score, source, approval_status) are
// sent to the backend so the file matches the list the user is looking at.
const ExportMenu = ({ filters = {}, count }) => {
  const { notify } = useToast();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(null);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc); };
  }, [open]);

  const run = async (fmt) => {
    setOpen(false);
    setBusy(fmt);
    try {
      const name = await downloadExport(fmt, filters);
      notify({ type: 'success', title: 'Export ready', message: `Downloaded ${name}.` });
    } catch (err) {
      notify({ type: 'error', title: 'Export failed', message: err.message });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="menu" ref={ref}>
      <button type="button" className="btn btn-outline" aria-haspopup="menu" aria-expanded={open}
        onClick={() => setOpen((o) => !o)} disabled={Boolean(busy)}>
        {busy ? <Spinner size={14} label="Exporting" /> : <Download size={15} />}
        {busy ? `Exporting ${busy.toUpperCase()}...` : 'Export'}
        <ChevronDown size={14} />
      </button>
      {open && (
        <div className="menu-list" role="menu">
          <div className="menu-note">
            {count != null ? `${count} job${count === 1 ? '' : 's'} ` : 'Jobs '}matching the status, score, source and decision filters
          </div>
          {FORMATS.map(({ key, label, hint, Icon }) => (
            <button key={key} type="button" role="menuitem" className="menu-item" onClick={() => run(key)}>
              <Icon size={16} />
              <span><span className="menu-item-label">{label}</span><span className="menu-item-hint">{hint}</span></span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

export default ExportMenu;
